from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, ClassVar, NewType, Protocol

import msgspec

from asyncqueue._types import TResult
from asyncqueue._util import utc_now
from asyncqueue.tasks import TaskDefinition, TaskInstance

Deserializer = Callable[[bytes], TResult]
Serializer = Callable[[TResult], bytes]

SerializationBackendId = NewType("SerializationBackendId", str)


class SerializationBackend(Protocol[TResult]):
    id: ClassVar[SerializationBackendId]

    def serialize(self, value: TResult) -> bytes: ...

    def deserialize(self, value: bytes, type: type[TResult]) -> TResult: ...

    def serializable(self, value: TResult) -> bool: ...


def serialize(
    value: object,
    default_backend: SerializationBackend[object],
    backends: Mapping[SerializationBackendId, SerializationBackend[object]],
) -> tuple[SerializationBackendId, bytes]:
    for backend in backends.values():
        if backend.serializable(value):
            return backend.id, backend.serialize(value)

    return default_backend.id, default_backend.serialize(value)


class TaskRecord(msgspec.Struct, kw_only=True):
    id: str
    task_name: str
    requeue_count: int = 0
    enqueue_time: datetime
    args: tuple[tuple[SerializationBackendId, bytes], ...]
    kwargs: dict[str, tuple[SerializationBackendId, bytes]]


def serialize_task(
    task: TaskInstance[Any, Any],
    default_backend: SerializationBackend[Any],
    serialization_backends: Mapping[
        SerializationBackendId,
        SerializationBackend[Any],
    ],
) -> TaskRecord:
    args = tuple(
        serialize(
            value,
            default_backend=default_backend,
            backends=serialization_backends,
        )
        for value in task.args
    )
    kwargs = {
        key: serialize(
            value,
            default_backend=default_backend,
            backends=serialization_backends,
        )
        for key, value in task.kwargs.items()
    }
    return TaskRecord(
        id=str(uuid.uuid4()),
        task_name=task.task.params.name,
        enqueue_time=utc_now(),
        args=args,
        kwargs=kwargs,
    )


def deserialize_task(
    task_definition: TaskDefinition[Any, Any],
    task: TaskRecord,
    serialization_backends: Mapping[
        SerializationBackendId,
        SerializationBackend[Any],
    ],
) -> tuple[tuple[object, ...], dict[str, object]]:
    args = tuple(
        serialization_backends[backend_id].deserialize(value, type=arg_type)
        for (backend_id, value), arg_type in zip(
            task.args, task_definition.arg_types, strict=False
        )
    )
    kwargs = {
        key: serialization_backends[backend_id].deserialize(
            value, type=task_definition.kwarg_types[key]
        )
        for key, (backend_id, value) in task.kwargs.items()
    }
    return args, kwargs
