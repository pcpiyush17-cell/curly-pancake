from __future__ import annotations

from uuid import uuid4

from mira.db import SQLiteRepository
from mira.models import (
    FocusSession,
    MiraResponse,
    ProgressReported,
    SessionSnapshot,
    Task,
    TaskCreate,
)
from mira.policy import DeterministicMiraPolicy


class MiraService:
    def __init__(
        self, repository: SQLiteRepository, policy: DeterministicMiraPolicy
    ) -> None:
        self.repository = repository
        self.policy = policy

    def create_task(self, data: TaskCreate) -> Task:
        task = Task(
            id=f"task-{uuid4().hex[:12]}",
            title=data.title,
            priority=data.priority,
        )
        return self.repository.create_task(task)

    def report_progress(
        self, session_id: str, event: ProgressReported
    ) -> MiraResponse:
        task = self.repository.update_task_progress(event.task_id, event.progress)
        focus = None
        if event.start_focus:
            focus_task = self.repository.get_task(event.focus_task_id or "")
            if focus_task is None:
                raise KeyError(event.focus_task_id)
            focus = FocusSession(
                id=f"focus-{uuid4().hex[:12]}",
                task_id=focus_task.id,
                planned_minutes=event.focus_minutes,
            )
            self.repository.start_focus_session(focus)

        response = self.policy.respond(task, focus)
        self.repository.record_event(
            session_id, event.type, event.model_dump(mode="json")
        )
        self.repository.record_event(
            session_id, "mira.response", response.model_dump(mode="json")
        )
        return response

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            tasks=self.repository.list_tasks(),
            active_focus_session=self.repository.active_focus_session(),
        )
