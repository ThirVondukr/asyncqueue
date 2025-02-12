import uuid

import pytest
from asyncqueue._util import utc_now
from asyncqueue.broker.inmemory import InMemoryBroker
from asyncqueue.serialization import TaskRecord
from asyncqueue.tasks import BrokerTask


@pytest.fixture
def broker() -> InMemoryBroker:
    return InMemoryBroker(max_buffer_size=100)


async def test_ctx(broker: InMemoryBroker) -> None:
    async with broker:
        pass


async def test_ack(broker: InMemoryBroker) -> None:
    task = TaskRecord(
        id=str(uuid.uuid4()),
        enqueue_time=utc_now(),
        task_name="some-name",
        args=(),
        kwargs={},
    )
    async with broker.ack_context(BrokerTask(task=task, meta=None)):
        pass
