from asyncqueue.broker.inmemory import InMemoryBroker
from asyncqueue.config import Configuration
from asyncqueue.publisher import Publisher
from asyncqueue.serialization import deserialize_task

from tests.tasks import noop_task, task_with_params
from tests.utils import capture_broker_messages


async def test_enqueue(broker: InMemoryBroker, publisher: Publisher) -> None:
    task_instance = noop_task()

    async with capture_broker_messages(broker, count=1) as messages:
        await publisher.enqueue(task=task_instance)

    assert len(messages) == 1
    message = messages[0]
    assert message.task.task_name == noop_task.params.name


async def test_enqueue_with_params(
    broker: InMemoryBroker,
    publisher: Publisher,
    configuration: Configuration,
) -> None:
    tasks = [task_with_params(a=i, b=str(i)) for i in range(10)]

    async with capture_broker_messages(broker, count=len(tasks)) as messages:
        for task_to_publish in tasks:
            await publisher.enqueue(task_to_publish)

    for task_, message in zip(tasks, messages, strict=True):
        assert message.task.task_name == task_with_params.params.name
        args, kwargs = deserialize_task(
            task_definition=task_.task,
            task=message.task,
            serialization_backends=configuration.serialization_backends,
        )
        assert task_.args == args
        assert task_.kwargs == kwargs
