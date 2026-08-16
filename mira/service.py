from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from mira.db import SQLiteRepository
from mira.models import (
    FocusSession,
    Goal,
    GoalCreate,
    Commitment,
    CommitmentCreate,
    MiraResponse,
    ProgressReported,
    SessionSnapshot,
    Task,
    TaskCreate,
    TaskUpdate,
    utc_now,
)
from mira.policy import DeterministicMiraPolicy
from mira.reasoning import MiraContext, SafeReasoningEngine, build_reasoning_engine


class MiraService:
    def __init__(
        self,
        repository: SQLiteRepository,
        policy: DeterministicMiraPolicy,
        reasoning: SafeReasoningEngine | None = None,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.reasoning = reasoning or build_reasoning_engine(policy)

    def create_task(self, data: TaskCreate) -> Task:
        task = Task(
            id=f"task-{uuid4().hex[:12]}",
            title=data.title,
            priority=data.priority,
            goal_id=data.goal_id,
        )
        return self.repository.create_task(task)

    def update_task(self, task_id: str, data: TaskUpdate) -> Task:
        return self.repository.update_task(
            task_id, title=data.title, priority=data.priority, goal_id=data.goal_id
        )

    def create_goal(self, data: GoalCreate) -> Goal:
        return self.repository.create_goal(
            Goal(id=f"goal-{uuid4().hex[:12]}", title=data.title)
        )

    def update_goal_status(self, goal_id: str, status: str) -> Goal:
        return self.repository.update_goal_status(goal_id, status)

    def create_commitment(self, data: CommitmentCreate) -> Commitment:
        return self.repository.create_commitment(
            Commitment(
                id=f"commitment-{uuid4().hex[:12]}",
                task_id=data.task_id,
                statement=data.statement,
                due_at=data.due_at,
            )
        )

    def resolve_commitment(self, commitment_id: str, kept: bool) -> Commitment:
        return self.repository.resolve_commitment(commitment_id, kept)

    def archive_task(self, task_id: str) -> Task:
        active_focus = self.repository.active_focus_session()
        if active_focus and active_focus.task_id == task_id:
            raise ValueError("End the active Focus session before archiving its task")
        return self.repository.archive_task(task_id)

    def transition_focus(self, session_id: str, action: str) -> FocusSession:
        session = self.repository.get_focus_session(session_id)
        if session is None:
            raise KeyError(session_id)
        now = utc_now()
        if action == "pause" and session.status == "active":
            session.status = "paused"
            session.paused_at = now
        elif action == "resume" and session.status == "paused" and session.paused_at:
            session.started_at += now - session.paused_at
            session.status = "active"
            session.paused_at = None
        elif action in {"complete", "cancel"} and session.status in {"active", "paused"}:
            session.status = "completed" if action == "complete" else "cancelled"
            session.ended_at = now
            session.paused_at = None
        else:
            raise ValueError(f"Cannot {action} a {session.status} Focus session")
        return self.repository.save_focus_session(session)

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

        context = MiraContext(
            event=event,
            current_task=task,
            goals=self.repository.list_goals(),
            commitments=self.repository.list_commitments(),
            active_focus_session=focus or self.repository.active_focus_session(),
        )
        response = self.reasoning.respond(context)
        self.repository.record_event(
            session_id, event.type, event.model_dump(mode="json")
        )
        self.repository.record_event(
            session_id, "mira.response", response.model_dump(mode="json")
        )
        return response

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            tasks=[
                task
                for task in self.repository.list_tasks()
                if task.status != "archived"
            ],
            goals=self.repository.list_goals(),
            commitments=self.repository.list_commitments(),
            active_focus_session=self.repository.active_focus_session(),
            focus_history=self.repository.focus_history(),
        )
