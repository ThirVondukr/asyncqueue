import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Annotated, Self

import msgspec.json
from redis.asyncio import Redis
from typing_extensions import Doc

from asyncqueue.broker.abc import Broker
from asyncqueue.config import Configuration
from asyncqueue.serialization import TaskRecord
from asyncqueue.tasks import BrokerTask

if TYPE_CHECKING:
    RedisClient = Redis[bytes]
else:
    RedisClient = Redis


@dataclasses.dataclass(kw_only=True, slots=True)
class RedisMeta:
    id: str


@dataclasses.dataclass(kw_only=True, slots=True)
class RedisBrokerConfig:
    stream_name: Annotated[str, Doc("Stream name in redis (key name)")] = "async-queue"
    group_name: Annotated[
        str,
        Doc(
            "Redis stream group name, there usually shouldn't be a need to change it. "
            "See <https://redis.io/docs/latest/commands/xgroup-create/>"
        ),
    ] = "default"
    xread_block_time: Annotated[
        timedelta, Doc("BLOCK parameter passed to redis XREAD command")
    ] = timedelta(seconds=1)
    xread_count: Annotated[
        int,
        Doc("Amount of entries to read from stream at once"),
    ] = 1


class RedisBroker(Broker):
    def __init__(
        self,
        *,
        redis: Annotated[RedisClient, Doc("Instance of redis")],
        broker_config: Annotated[
            RedisBrokerConfig | None, Doc("Redis specific configuration")
        ] = None,
        consumer_name: Annotated[
            str,
            Doc(
                r"Name of stream consumer, if you run multiple workers you'd need to change that. "
                "<https://redis.io/docs/latest/develop/data-types/streams/#consumer-groups> and "
                "<https://redis.io/docs/latest/develop/data-types/streams/#differences-with-kafka-tm-partitions>"
            ),
        ],
        max_concurrency: Annotated[
            int,
            Doc("Max amount of tasks being concurrently added into redis stream"),
        ] = 20,
    ) -> None:
        self._redis = redis
        self._broker_config = broker_config or RedisBrokerConfig()
        self._consumer_name = consumer_name
        self._sem = asyncio.Semaphore(max_concurrency)

        self._is_initialized = False
        self._stop = asyncio.Event()

    async def enqueue(self, task: TaskRecord) -> None:
        async with self._sem:
            await self._redis.xadd(
                self._broker_config.stream_name,
                {"value": msgspec.json.encode(task)},
            )

    async def __aenter__(self) -> Self:
        if self._is_initialized:
            return self

        stream_exists = await self._redis.exists(self._broker_config.stream_name) != 0
        group_exists = (
            self._broker_config.group_name
            in (
                info["name"].decode()
                for info in await self._redis.xinfo_groups(
                    self._broker_config.stream_name
                )  # type: ignore[no-untyped-call]
            )
            if stream_exists
            else False
        )
        if not stream_exists or not group_exists:
            await self._redis.xgroup_create(
                name=self._broker_config.stream_name,
                groupname=self._broker_config.group_name,
                mkstream=True,
            )
        await self._redis.xgroup_createconsumer(  # type: ignore[no-untyped-call]
            self._broker_config.stream_name,
            self._broker_config.group_name,
            self._consumer_name,
        )
        self._is_initialized = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._stop.set()

    async def read(self) -> Sequence[BrokerTask[RedisMeta]]:
        xread_result = await self._redis.xreadgroup(
            self._broker_config.group_name,
            self._consumer_name,
            {self._broker_config.stream_name: ">"},
            count=self._broker_config.xread_count,
            block=int(self._broker_config.xread_block_time.total_seconds() * 1000),
        )
        result = []
        for _, records in xread_result:
            for record_id, record in records:
                task = msgspec.json.decode(record[b"value"], type=TaskRecord)
                result.append(
                    BrokerTask(
                        task=task,
                        meta=RedisMeta(id=record_id),
                    )
                )
        return result

    async def run_worker_maintenance_tasks(
        self,
        stop: asyncio.Event,
        config: Configuration,
    ) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                self._maintenance_claim_pending_records(
                    stop=stop,
                    timeout_interval=config.task.timeout_interval,
                ),
            )

    async def _maintenance_claim_pending_records(
        self,
        stop: asyncio.Event,
        timeout_interval: timedelta,
    ) -> None:
        """Requeues messages that weren't ACKed in time."""
        stop_task = asyncio.create_task(stop.wait())
        while True:
            claimed = await self._redis.xautoclaim(
                self._broker_config.stream_name,
                self._broker_config.group_name,
                self._consumer_name,
                count=1000,
                min_idle_time=int(timeout_interval.total_seconds() * 1000),
            )
            logging.debug("Claimed %s", claimed)

            _, messages, _ = claimed
            for record_id, record in messages:
                task = msgspec.json.decode(record[b"value"], type=TaskRecord)
                task.requeue_count += 1
                await self.enqueue(task)
                await self._redis.xack(  # type: ignore[no-untyped-call]
                    self._broker_config.stream_name,
                    self._broker_config.group_name,
                    record_id,
                )

            sleep_task = asyncio.create_task(
                asyncio.sleep(timeout_interval.total_seconds())
            )
            await asyncio.wait(
                {stop_task, sleep_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stop.is_set():
                return

    @contextlib.asynccontextmanager
    async def ack_context(self, task: BrokerTask[RedisMeta]) -> AsyncIterator[None]:
        yield
        await self._redis.xack(  # type: ignore[no-untyped-call]
            self._broker_config.stream_name,
            self._broker_config.group_name,
            task.meta.id,
        )
        logging.info("Acked %s, redis id %s", task.task.id, task.meta.id)

    async def tasks_healthcheck(self, *tasks: BrokerTask[RedisMeta]) -> None:
        task_ids = [task.meta.id for task in tasks]
        await self._redis.xclaim(  # type: ignore[no-untyped-call]
            self._broker_config.stream_name,
            self._broker_config.group_name,
            self._consumer_name,
            min_idle_time=0,
            message_ids=task_ids,
        )
