import asyncio
import contextlib
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Self

import anyio

from asyncqueue.broker.abc import Broker
from asyncqueue.config import Configuration
from asyncqueue.serialization import TaskRecord
from asyncqueue.tasks import BrokerTask


class InMemoryBroker(Broker):
    def __init__(self, max_buffer_size: int) -> None:
        self._send, self._recv = anyio.create_memory_object_stream[BrokerTask[object]](
            max_buffer_size=max_buffer_size,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def enqueue(self, task: TaskRecord) -> None:
        await self._send.send(BrokerTask(task=task, meta=None))

    async def read(self) -> Sequence[BrokerTask[object]]:
        return (await self._recv.receive(),)

    def ack_context(
        self,
        task: BrokerTask[object],  # noqa: ARG002
    ) -> AbstractAsyncContextManager[None]:
        return contextlib.nullcontext()

    async def run_worker_maintenance_tasks(
        self,
        stop: asyncio.Event,
        config: Configuration,
    ) -> None:  # pragma: no cover
        pass

    async def tasks_healthcheck(
        self,
        *tasks: BrokerTask[object],
    ) -> None:  # pragma: no cover
        pass
