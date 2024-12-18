from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncqueue.router import TaskRouter
    from asyncqueue.task import TaskDefinition


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def extract_tasks(
    tasks: TaskRouter | Sequence[TaskDefinition[Any, Any]],
) -> Sequence[TaskDefinition[Any, Any]]:
    from asyncqueue.router import TaskRouter

    if isinstance(tasks, TaskRouter):
        return tuple(tasks.tasks.values())
    return tasks
