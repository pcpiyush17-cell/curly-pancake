from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class MiraState(StrEnum):
    SUPPORTIVE = "SUPPORTIVE"
    CHALLENGING = "CHALLENGING"
    CELEBRATING = "CELEBRATING"
    FOCUSING = "FOCUSING"
    CURIOUS = "CURIOUS"


class Task(BaseModel):
    id: str
    title: str
    status: TaskStatus = TaskStatus.TODO
    progress: float = Field(default=0, ge=0, le=1)
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Goal(BaseModel):
    id: str
    title: str
    status: Literal["active", "achieved", "paused"] = "active"
    created_at: datetime = Field(default_factory=utc_now)


class Commitment(BaseModel):
    id: str
    task_id: str | None = None
    statement: str
    promised_at: datetime = Field(default_factory=utc_now)
    due_at: datetime | None = None
    kept: bool | None = None


class Memory(BaseModel):
    id: str
    kind: Literal["preference", "pattern", "fact", "reflection"]
    content: str
    importance: float = Field(default=0.5, ge=0, le=1)
    created_at: datetime = Field(default_factory=utc_now)


class FocusSession(BaseModel):
    id: str
    task_id: str
    planned_minutes: int = Field(ge=1, le=240)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    status: Literal["active", "completed", "cancelled"] = "active"


class Expression(BaseModel):
    primary: Literal[
        "soft_smile", "raised_eyebrow", "attentive", "focused", "neutral"
    ]
    intensity: float = Field(ge=0, le=1)


class Gesture(BaseModel):
    type: Literal["small_nod", "subtle_head_tilt", "still", "lean_in"]
    intensity: float = Field(ge=0, le=1)


class UpdateTaskAction(BaseModel):
    type: Literal["update_task"] = "update_task"
    task_id: str
    status: TaskStatus
    progress: float = Field(ge=0, le=1)


class HighlightTaskAction(BaseModel):
    type: Literal["highlight_task"] = "highlight_task"
    task_id: str


class StartFocusAction(BaseModel):
    type: Literal["start_focus_mode"] = "start_focus_mode"
    focus_session_id: str
    task_id: str
    duration_minutes: int


UIAction = Annotated[
    UpdateTaskAction | HighlightTaskAction | StartFocusAction,
    Field(discriminator="type"),
]


class MiraResponse(BaseModel):
    speech: str
    state: MiraState
    tone: Literal["warm", "direct", "wry", "calm", "focused"]
    tone_intensity: float = Field(ge=0, le=1)
    expression: Expression
    gesture: Gesture
    ui_actions: list[UIAction] = Field(default_factory=list)
    pause_before_ms: int = Field(default=0, ge=0, le=3000)


class ProgressReported(BaseModel):
    type: Literal["progress.reported"] = "progress.reported"
    source: Literal["voice", "text"]
    task_id: str
    transcript: str = Field(min_length=1, max_length=2000)
    progress: float = Field(ge=0, le=1)
    start_focus: bool = False
    focus_task_id: str | None = None
    focus_minutes: int = Field(default=25, ge=1, le=240)

    @model_validator(mode="after")
    def focus_target_is_present(self) -> "ProgressReported":
        if self.start_focus and not self.focus_task_id:
            raise ValueError("focus_task_id is required when start_focus is true")
        return self


class SnapshotRequested(BaseModel):
    type: Literal["session.snapshot.requested"] = "session.snapshot.requested"


ClientEvent = Annotated[
    ProgressReported | SnapshotRequested, Field(discriminator="type")
]


class SessionSnapshot(BaseModel):
    tasks: list[Task]
    active_focus_session: FocusSession | None = None

