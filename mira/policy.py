from __future__ import annotations

from mira.models import (
    Expression,
    FocusSession,
    Gesture,
    HighlightTaskAction,
    MiraResponse,
    MiraState,
    StartFocusAction,
    Task,
    UpdateTaskAction,
)


class DeterministicMiraPolicy:
    """Testable v0.1 stand-in for the future language/reasoning adapter."""

    def respond(
        self, task: Task, focus: FocusSession | None = None
    ) -> MiraResponse:
        actions = [
            UpdateTaskAction(
                task_id=task.id, status=task.status, progress=task.progress
            )
        ]

        if focus:
            actions.extend(
                [
                    HighlightTaskAction(task_id=focus.task_id),
                    StartFocusAction(
                        focus_session_id=focus.id,
                        task_id=focus.task_id,
                        duration_minutes=focus.planned_minutes,
                    ),
                ]
            )
            return MiraResponse(
                speech=(
                    f"Nice. {task.title} is done. Focus Mode is on for "
                    f"{focus.planned_minutes} minutes. Let's make the next one count."
                ),
                state=MiraState.FOCUSING,
                tone="focused",
                tone_intensity=0.62,
                expression=Expression(primary="focused", intensity=0.55),
                gesture=Gesture(type="small_nod", intensity=0.35),
                ui_actions=actions,
                pause_before_ms=250,
            )

        if task.progress == 1:
            return MiraResponse(
                speech=f"Nice. {task.title} was the difficult one. What's next?",
                state=MiraState.CELEBRATING,
                tone="warm",
                tone_intensity=0.45,
                expression=Expression(primary="soft_smile", intensity=0.5),
                gesture=Gesture(type="small_nod", intensity=0.3),
                ui_actions=actions,
                pause_before_ms=150,
            )

        if task.progress == 0:
            return MiraResponse(
                speech="Okay. What actually got in the way?",
                state=MiraState.CHALLENGING,
                tone="direct",
                tone_intensity=0.6,
                expression=Expression(primary="raised_eyebrow", intensity=0.45),
                gesture=Gesture(type="subtle_head_tilt", intensity=0.3),
                ui_actions=actions,
                pause_before_ms=600,
            )

        percent = round(task.progress * 100)
        return MiraResponse(
            speech=f"Good. {percent} percent is real progress. Name the next step.",
            state=MiraState.SUPPORTIVE,
            tone="calm",
            tone_intensity=0.4,
            expression=Expression(primary="attentive", intensity=0.4),
            gesture=Gesture(type="small_nod", intensity=0.25),
            ui_actions=actions,
            pause_before_ms=200,
        )

