from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ServerEnvelope(BaseModel):
    protocol_version: Literal["0.1"]
    event_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=100)
    timestamp: datetime
    correlation_id: str | None = Field(default=None, max_length=100)
    requires_ack: bool
    payload: dict[str, Any]


class ClientEnvelope(BaseModel):
    protocol_version: Literal["0.1"]
    event_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=100)
    timestamp: datetime
    correlation_id: str | None = Field(default=None, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class ClientAck(BaseModel):
    event_id: str = Field(min_length=1, max_length=100)
    status: Literal["applied", "failed"]


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


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
    goal_id: str | None = None
    due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    priority: int = Field(default=3, ge=1, le=5)
    goal_id: str | None = None

    @field_validator("title")
    @classmethod
    def title_is_not_blank(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    priority: int | None = Field(default=None, ge=1, le=5)
    goal_id: str | None = None

    @field_validator("title")
    @classmethod
    def updated_title_is_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title


class Goal(BaseModel):
    id: str
    title: str
    status: Literal["active", "achieved", "paused"] = "active"
    created_at: datetime = Field(default_factory=utc_now)


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)

    @field_validator("title")
    @classmethod
    def goal_title_is_not_blank(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title


class Commitment(BaseModel):
    id: str
    task_id: str | None = None
    statement: str
    promised_at: datetime = Field(default_factory=utc_now)
    due_at: datetime | None = None
    kept: bool | None = None


class CommitmentCreate(BaseModel):
    statement: str = Field(min_length=1, max_length=300)
    task_id: str | None = None
    due_at: datetime | None = None

    @field_validator("statement")
    @classmethod
    def statement_is_not_blank(cls, value: str) -> str:
        statement = value.strip()
        if not statement:
            raise ValueError("statement must not be blank")
        return statement


class Memory(BaseModel):
    id: str
    kind: Literal["preference", "pattern", "fact", "reflection"]
    content: str
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: Literal["user", "reflection", "inferred"] = "user"
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryCreate(BaseModel):
    kind: Literal["preference", "pattern", "fact", "reflection"]
    content: str = Field(min_length=1, max_length=500)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def memory_content_is_not_blank(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("content must not be blank")
        return content


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=500)
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def updated_memory_is_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        content = value.strip()
        if not content:
            raise ValueError("content must not be blank")
        return content


class FocusSession(BaseModel):
    id: str
    task_id: str
    planned_minutes: int = Field(ge=1, le=240)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    paused_at: datetime | None = None
    status: Literal["active", "paused", "completed", "cancelled"] = "active"


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


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ConversationMessage(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "mira"]
    content: str = Field(min_length=1, max_length=2000)
    created_at: datetime = Field(default_factory=utc_now)


class ConversationMessageSent(BaseModel):
    type: Literal["conversation.message.sent"] = "conversation.message.sent"
    source: Literal["voice", "text"] = "text"
    text: str = Field(min_length=1, max_length=2000)
    task_id: str | None = None


class ProposalOption(BaseModel):
    id: str
    label: str
    action: Literal["start_focus", "resume_focus", "mark_task_blocked", "dismiss"]
    task_id: str | None = None
    focus_session_id: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=240)


class ConversationProposal(BaseModel):
    id: str
    session_id: str
    prompt: str
    options: list[ProposalOption] = Field(min_length=1, max_length=4)
    status: Literal["pending", "applied", "dismissed"] = "pending"
    selected_option_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ProposalSelected(BaseModel):
    type: Literal["conversation.proposal.selected"] = "conversation.proposal.selected"
    proposal_id: str
    option_id: str
    source: Literal["voice", "text"] = "text"


class ConversationTurn(BaseModel):
    user_message: ConversationMessage
    mira_message: ConversationMessage
    response: MiraResponse
    proposal: ConversationProposal | None = None


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


class VoiceLifecycleEvent(BaseModel):
    type: Literal[
        "user.speech.started",
        "user.speech.completed",
        "mira.speech.started",
        "mira.speech.completed",
        "mira.speech.interrupted",
    ]
    transcript: str | None = Field(default=None, max_length=2000)


ClientEvent = Annotated[
    ProgressReported | ConversationMessageSent | ProposalSelected | SnapshotRequested | VoiceLifecycleEvent,
    Field(discriminator="type"),
]


class DailyRhythmSettings(BaseModel):
    enabled: bool = False
    morning_time: str = Field(default="08:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    midday_time: str = Field(default="13:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    evening_time: str = Field(default="20:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def times_are_in_order(self) -> "DailyRhythmSettings":
        if not self.morning_time < self.midday_time < self.evening_time:
            raise ValueError("Daily Rhythm times must be in morning, midday, evening order")
        return self


class PrepItem(BaseModel):
    id: str
    week: int = Field(ge=1, le=12)
    track: Literal["dsa", "fundamentals", "design", "practice", "review"]
    title: str
    description: str
    planned_minutes: int = Field(ge=15, le=1200)
    status: Literal["planned", "in_progress", "completed", "skipped"] = "planned"
    task_id: str | None = None
    completed_at: datetime | None = None


class PrepItemUpdate(BaseModel):
    status: Literal["planned", "in_progress", "completed", "skipped"]


class PrepWeek(BaseModel):
    number: int = Field(ge=1, le=12)
    starts_on: str
    ends_on: str
    theme: str
    checkpoint: str | None = None
    items: list[PrepItem] = Field(default_factory=list)


class PrepSnapshot(BaseModel):
    title: str = "MLE Interview Preparation"
    starts_on: str = "2026-08-31"
    ends_on: str = "2026-11-22"
    total_minutes: int = 14400
    completed_minutes: int = 0
    current_week: int = 1
    weeks: list[PrepWeek] = Field(default_factory=list)


class SessionSnapshot(BaseModel):
    tasks: list[Task]
    goals: list[Goal] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    memories: list[Memory] = Field(default_factory=list)
    active_focus_session: FocusSession | None = None
    focus_history: list[FocusSession] = Field(default_factory=list)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    pending_proposal: ConversationProposal | None = None
    daily_rhythm: DailyRhythmSettings = Field(default_factory=DailyRhythmSettings)

