from __future__ import annotations

import os
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from mira.models import (
    Commitment,
    Expression,
    FocusSession,
    Gesture,
    Goal,
    MiraResponse,
    MiraState,
    Memory,
    ProgressReported,
    Task,
)
from mira.policy import DeterministicMiraPolicy


PERSONA_INSTRUCTIONS = """
You are Mira, a desktop AI execution companion. You are a warm mentor and a
precise, occasionally witty challenger. Speak concisely. Do not use bubbly
assistant filler, exaggerated praise, shame, manipulation, romantic language,
exclusivity, or claims of consciousness. Challenge behavior and inconsistencies,
never the user's worth. Treat memories and interpretations as fallible. Use the
provided facts only. Return a structured response matching the requested schema.
The application, not you, decides and executes UI or persistence actions.
Never expose internal task IDs, raw field names, JSON, or the phrase "transcript".
Do not quote the user's message back to them. Keep speech to at most two short
sentences and roughly 45 words. Offer one clear observation or next move, not a
menu of options, unless the user explicitly asks for choices.
""".strip()


class MiraContext(BaseModel):
    event: ProgressReported
    current_task: Task
    goals: list[Goal] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    relevant_memories: list[Memory] = Field(default_factory=list)
    active_focus_session: FocusSession | None = None


class MiraPresentation(BaseModel):
    """Provider-owned speech and embodiment fields; every field is required."""

    speech: str
    state: MiraState
    tone: Literal["warm", "direct", "wry", "calm", "focused"]
    tone_intensity: float = Field(ge=0, le=1)
    expression: Expression
    gesture: Gesture
    pause_before_ms: int = Field(ge=0, le=3000)


class ReasoningProvider(Protocol):
    name: str

    def generate(self, context: MiraContext) -> MiraResponse: ...


class DeterministicReasoningProvider:
    name = "deterministic"

    def __init__(self, policy: DeterministicMiraPolicy) -> None:
        self.policy = policy

    def generate(self, context: MiraContext) -> MiraResponse:
        return self.policy.respond(context.current_task, context.active_focus_session)


class OpenAIReasoningProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        timeout = float(os.getenv("MIRA_OPENAI_TIMEOUT_SECONDS", "20"))
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        self.model = model

    def generate(self, context: MiraContext) -> MiraResponse:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": PERSONA_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": context.model_dump_json(exclude_none=True),
                },
            ],
            text_format=MiraPresentation,
        )
        if response.output_parsed is None:
            raise ValueError("Reasoning provider returned no structured response")
        presentation = response.output_parsed
        return MiraResponse(
            speech=presentation.speech,
            state=presentation.state,
            tone=presentation.tone,
            tone_intensity=presentation.tone_intensity,
            expression=presentation.expression,
            gesture=presentation.gesture,
            pause_before_ms=presentation.pause_before_ms,
            ui_actions=[],
        )


class SafeReasoningEngine:
    def __init__(
        self,
        primary: ReasoningProvider,
        fallback: DeterministicReasoningProvider,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_provider = fallback.name
        self.last_error: dict[str, str | int | None] | None = None

    @property
    def configured_provider(self) -> str:
        return self.primary.name

    def respond(self, context: MiraContext) -> MiraResponse:
        authoritative = self.fallback.generate(context)
        try:
            proposed = self.primary.generate(context)
            self.last_provider = self.primary.name
            self.last_error = None
            return proposed.model_copy(update={"ui_actions": authoritative.ui_actions})
        except Exception as error:
            self.last_provider = self.fallback.name
            self.last_error = {
                "type": type(error).__name__,
                "status_code": getattr(error, "status_code", None),
                "code": getattr(error, "code", None),
            }
            return authoritative


def build_reasoning_engine(
    policy: DeterministicMiraPolicy | None = None,
) -> SafeReasoningEngine:
    policy = policy or DeterministicMiraPolicy()
    fallback = DeterministicReasoningProvider(policy)
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MIRA_OPENAI_MODEL")
    if not api_key or not model:
        return SafeReasoningEngine(fallback, fallback)
    try:
        primary: ReasoningProvider = OpenAIReasoningProvider(api_key, model)
    except ImportError:
        primary = fallback
    return SafeReasoningEngine(primary, fallback)
