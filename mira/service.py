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
    ConversationMessage,
    ConversationMessageSent,
    ConversationProposal,
    ConversationTurn,
    DailyRhythmSettings,
    Expression,
    MiraResponse,
    MiraState,
    Gesture,
    Memory,
    MemoryCreate,
    MemoryUpdate,
    PrepItemUpdate,
    PrepSnapshot,
    ProgressReported,
    ProposalOption,
    ProposalSelected,
    SessionSnapshot,
    Task,
    TaskCreate,
    TaskUpdate,
    TaskStatus,
    StartFocusAction,
    UpdateTaskAction,
    VoiceLifecycleEvent,
    utc_now,
)
from mira.policy import DeterministicMiraPolicy
from mira.prep import active_week, canonical_weeks
from mira.reasoning import (
    ConversationContext,
    MiraContext,
    SafeReasoningEngine,
    build_reasoning_engine,
)


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

    def update_daily_rhythm(
        self, settings: DailyRhythmSettings
    ) -> DailyRhythmSettings:
        return self.repository.save_daily_rhythm_settings(settings)

    def prep_snapshot(self) -> PrepSnapshot:
        weeks = canonical_weeks()
        self.repository.seed_prep_items([item for week in weeks for item in week.items])
        persisted = {item.id: item for item in self.repository.list_prep_items()}
        for week in weeks:
            for item in week.items:
                saved = persisted[item.id]
                item.status = saved.status
                item.task_id = saved.task_id
                item.completed_at = saved.completed_at
        completed = sum(
            item.planned_minutes for item in persisted.values()
            if item.status == "completed"
        )
        return PrepSnapshot(
            completed_minutes=completed, current_week=active_week(), weeks=weeks
        )

    def update_prep_item(self, item_id: str, data: PrepItemUpdate):
        self.prep_snapshot()
        return self.repository.update_prep_item(item_id, data.status)

    def queue_prep_item(self, item_id: str):
        self.prep_snapshot()
        item = self.repository.get_prep_item(item_id)
        if item is None:
            raise KeyError(item_id)
        if item.task_id:
            task = self.repository.get_task(item.task_id)
            if task is not None:
                return {"item": item, "task": task}
        task = self.create_task(TaskCreate(title=item.title, priority=1))
        item = self.repository.link_prep_item(item.id, task.id)
        return {"item": item, "task": task}

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

    def converse(
        self, session_id: str, event: ConversationMessageSent
    ) -> ConversationTurn:
        pending = self.repository.pending_conversation_proposal(session_id)
        option_id = self._natural_proposal_choice(event.text, pending)
        if pending and option_id:
            return self.select_proposal(
                session_id,
                ProposalSelected(
                    proposal_id=pending.id, option_id=option_id, source=event.source
                ),
                user_text=event.text,
            )
        current_task = None
        if event.task_id:
            current_task = self.repository.get_task(event.task_id)
            if current_task is None:
                raise KeyError(event.task_id)
        user_message = self.repository.save_conversation_message(
            ConversationMessage(
                id=f"message-{uuid4().hex[:12]}", session_id=session_id,
                role="user", content=event.text,
            )
        )
        context = ConversationContext(
            event=event,
            recent_messages=self.repository.conversation_messages(session_id, 12),
            current_task=current_task,
            active_focus_session=self.repository.active_focus_session(),
            relevant_memories=self.relevant_memories(event.text),
        )
        response = self.reasoning.respond_conversation(context)
        proposal = self._build_proposal(session_id, event, current_task)
        if proposal:
            response = response.model_copy(
                update={
                    "speech": proposal.prompt,
                    "state": MiraState.CURIOUS,
                    "tone": "direct",
                    "expression": Expression(primary="attentive", intensity=0.5),
                    "gesture": Gesture(type="small_nod", intensity=0.2),
                }
            )
        mira_message = self.repository.save_conversation_message(
            ConversationMessage(
                id=f"message-{uuid4().hex[:12]}", session_id=session_id,
                role="mira", content=response.speech,
            )
        )
        self.repository.record_event(
            session_id, event.type, event.model_dump(mode="json")
        )
        self.repository.record_event(
            session_id, "conversation.mira.responded",
            response.model_dump(mode="json"),
        )
        return ConversationTurn(
            user_message=user_message,
            mira_message=mira_message,
            response=response,
            proposal=proposal,
        )

    def _build_proposal(
        self,
        session_id: str,
        event: ConversationMessageSent,
        task: Task | None,
    ) -> ConversationProposal | None:
        if not task:
            return None
        normalized = event.text.lower()
        struggle_terms = (
            "wasn't able", "was not able", "couldn't", "could not", "didn't do",
            "did not do", "unable", "stuck", "not finished", "not complete",
        )
        if not any(term in normalized for term in struggle_terms):
            return None
        active_focus = self.repository.active_focus_session()
        options: list[ProposalOption] = []
        if active_focus and active_focus.status == "paused":
            options.append(
                ProposalOption(
                    id="a", label="Resume the paused Focus session",
                    action="resume_focus", focus_session_id=active_focus.id,
                )
            )
        elif not active_focus:
            options.append(
                ProposalOption(
                    id="a", label=f"Start 25 minutes on {task.title}",
                    action="start_focus", task_id=task.id, duration_minutes=25,
                )
            )
        options.extend(
            [
                ProposalOption(
                    id="b", label=f"Mark {task.title} as blocked",
                    action="mark_task_blocked", task_id=task.id,
                ),
                ProposalOption(id="c", label="Keep talking first", action="dismiss"),
            ]
        )
        proposal = ConversationProposal(
            id=f"proposal-{uuid4().hex[:12]}", session_id=session_id,
            prompt="That didn't move. Choose the next honest action-I'll only change it after you confirm.",
            options=options,
        )
        return self.repository.save_conversation_proposal(proposal)

    @staticmethod
    def _natural_proposal_choice(
        text: str, proposal: ConversationProposal | None
    ) -> str | None:
        if not proposal:
            return None
        normalized = text.lower().strip().replace(".", "")
        if normalized in {"yes", "yes do it", "do it", "okay", "ok", "confirm"}:
            return proposal.options[0].id
        for option in proposal.options:
            if normalized in {option.id, f"option {option.id}", f"choose {option.id}"}:
                return option.id
        return None

    def select_proposal(
        self,
        session_id: str,
        event: ProposalSelected,
        *,
        user_text: str | None = None,
    ) -> ConversationTurn:
        proposal = self.repository.get_conversation_proposal(event.proposal_id)
        if proposal is None or proposal.session_id != session_id:
            raise KeyError(event.proposal_id)
        if proposal.status != "pending":
            raise ValueError("This proposal has already been resolved")
        option = next((item for item in proposal.options if item.id == event.option_id), None)
        if option is None:
            raise KeyError(event.option_id)
        ui_actions = []
        if option.action == "start_focus" and option.task_id and option.duration_minutes:
            focus = FocusSession(
                id=f"focus-{uuid4().hex[:12]}", task_id=option.task_id,
                planned_minutes=option.duration_minutes,
            )
            self.repository.start_focus_session(focus)
            ui_actions.append(
                StartFocusAction(
                    focus_session_id=focus.id, task_id=focus.task_id,
                    duration_minutes=focus.planned_minutes,
                )
            )
            speech = f"Done. Focus Mode is on for {focus.planned_minutes} minutes."
        elif option.action == "resume_focus" and option.focus_session_id:
            focus = self.transition_focus(option.focus_session_id, "resume")
            ui_actions.append(
                StartFocusAction(
                    focus_session_id=focus.id, task_id=focus.task_id,
                    duration_minutes=focus.planned_minutes,
                )
            )
            speech = "Done. Your paused Focus session is running again."
        elif option.action == "mark_task_blocked" and option.task_id:
            task = self.repository.get_task(option.task_id)
            if task is None:
                raise KeyError(option.task_id)
            task.status = TaskStatus.BLOCKED
            self.repository.save_task(task)
            ui_actions.append(
                UpdateTaskAction(
                    task_id=task.id, status=task.status, progress=task.progress
                )
            )
            speech = f"Done. {task.title} is marked blocked. Now name the blocker."
        else:
            speech = "Okay. No changes made. Tell me what actually got in the way."
        proposal.status = "dismissed" if option.action == "dismiss" else "applied"
        proposal.selected_option_id = option.id
        self.repository.save_conversation_proposal(proposal)
        user_message = self.repository.save_conversation_message(
            ConversationMessage(
                id=f"message-{uuid4().hex[:12]}", session_id=session_id,
                role="user", content=user_text or option.label,
            )
        )
        focus_changed = option.action in {"start_focus", "resume_focus"}
        response = MiraResponse(
            speech=speech, state=MiraState.FOCUSING if focus_changed else MiraState.SUPPORTIVE,
            tone="focused" if focus_changed else "calm", tone_intensity=0.45,
            expression=Expression(primary="focused" if focus_changed else "attentive", intensity=0.45),
            gesture=Gesture(type="small_nod", intensity=0.25), ui_actions=ui_actions,
        )
        mira_message = self.repository.save_conversation_message(
            ConversationMessage(
                id=f"message-{uuid4().hex[:12]}", session_id=session_id,
                role="mira", content=speech,
            )
        )
        return ConversationTurn(
            user_message=user_message, mira_message=mira_message,
            response=response, proposal=proposal,
        )

    def snapshot(self, session_id: str = "dashboard") -> SessionSnapshot:
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
            conversation=self.repository.conversation_messages(session_id),
            pending_proposal=self.repository.pending_conversation_proposal(session_id),
            daily_rhythm=self.repository.daily_rhythm_settings(),
        )

