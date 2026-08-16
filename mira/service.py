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
    Memory,
    MemoryCreate,
    MemoryUpdate,
    ProgressReported,
    SessionSnapshot,
    Task,
    TaskCreate,
    TaskUpdate,
    VoiceLifecycleEvent,
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

    def create_memory(self, data: MemoryCreate) -> Memory:
        return self.repository.create_memory(
            Memory(
                id=f"memory-{uuid4().hex[:12]}",
                kind=data.kind,
                content=data.content,
                importance=data.importance,
                confidence=data.confidence,
                source="user",
                expires_at=data.expires_at,
            )
        )

    def update_memory(self, memory_id: str, data: MemoryUpdate) -> Memory:
        return self.repository.update_memory(
            memory_id,
            content=data.content,
            importance=data.importance,
            confidence=data.confidence,
            expires_at=data.expires_at,
        )

    def delete_memory(self, memory_id: str) -> None:
        self.repository.delete_memory(memory_id)

    def relevant_memories(self, text: str, limit: int = 5) -> list[Memory]:
        words = {word.strip(".,!?;:'\"").lower() for word in text.split()}
        words = {word for word in words if len(word) >= 3}
        scored: list[tuple[float, Memory]] = []
        for memory in self.repository.list_memories():
            memory_words = {
                word.strip(".,!?;:'\"").lower() for word in memory.content.split()
            }
            overlap = len(words & memory_words)
            score = overlap * 2 + memory.importance + memory.confidence * 0.5
            if overlap or memory.importance >= 0.8:
                scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [memory for _, memory in scored[:limit]]

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
            relevant_memories=self.relevant_memories(
                f"{event.transcript} {task.title}"
            ),
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

    def record_voice_event(
        self, session_id: str, event: VoiceLifecycleEvent
    ) -> None:
        self.repository.record_event(
            session_id, event.type, event.model_dump(mode="json")
        )

    def snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            tasks=[
                task
                for task in self.repository.list_tasks()
                if task.status != "archived"
            ],
            goals=self.repository.list_goals(),
            commitments=self.repository.list_commitments(),
            memories=self.repository.list_memories(),
            active_focus_session=self.repository.active_focus_session(),
            focus_history=self.repository.focus_history(),
        )
