from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from mira.models import (
    Commitment,
    FocusSession,
    Goal,
    Memory,
    Task,
    TaskStatus,
    utc_now,
)


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL CHECK(progress >= 0 AND progress <= 1),
    priority INTEGER NOT NULL,
    goal_id TEXT,
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
    ,FOREIGN KEY(goal_id) REFERENCES goals(id)
);
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY, task_id TEXT, statement TEXT NOT NULL,
    promised_at TEXT NOT NULL, due_at TEXT, kept INTEGER,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
    importance REAL NOT NULL, confidence REAL NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'user', expires_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, planned_minutes INTEGER NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT, paused_at TEXT, status TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS interaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbound_events (
    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbound_events (
    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
    envelope_json TEXT NOT NULL, requires_ack INTEGER NOT NULL,
    acknowledged_at TEXT, acknowledgement_status TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbound_events_pending
ON outbound_events(session_id, acknowledged_at) WHERE requires_ack = 1;
"""


class SQLiteRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            focus_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(focus_sessions)")
            }
            if "paused_at" not in focus_columns:
                connection.execute(
                    "ALTER TABLE focus_sessions ADD COLUMN paused_at TEXT"
                )
            task_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(tasks)")
            }
            if "goal_id" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN goal_id TEXT")
            memory_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(memories)")
            }
            for name, definition in {
                "confidence": "REAL NOT NULL DEFAULT 1",
                "source": "TEXT NOT NULL DEFAULT 'user'",
                "expires_at": "TEXT",
                "updated_at": "TEXT",
            }.items():
                if name not in memory_columns:
                    connection.execute(
                        f"ALTER TABLE memories ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                "UPDATE memories SET updated_at=created_at WHERE updated_at IS NULL"
            )
            connection.execute("PRAGMA optimize")

    def seed_demo_tasks(self) -> None:
        if self.list_tasks():
            return
        self.save_task(Task(id="task-ml", title="Finish ML assignment", priority=1))
        self.save_task(Task(id="task-dsa", title="Practice DSA", priority=2))

    def save_task(self, task: Task) -> None:
        task.updated_at = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO tasks
                (id,title,status,progress,priority,goal_id,due_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                status=excluded.status, progress=excluded.progress,
                priority=excluded.priority, goal_id=excluded.goal_id,
                due_at=excluded.due_at,
                updated_at=excluded.updated_at""",
                (
                    task.id, task.title, task.status.value, task.progress,
                    task.priority, task.goal_id, _dt(task.due_at), _dt(task.created_at),
                    _dt(task.updated_at),
                ),
            )

    def create_task(self, task: Task) -> Task:
        if self.get_task(task.id) is not None:
            raise ValueError(f"Task already exists: {task.id}")
        self.save_task(task)
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return _task(row) if row else None

    def list_tasks(self) -> list[Task]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY priority, created_at"
            ).fetchall()
        return [_task(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        *,
        title: str | None,
        priority: int | None,
        goal_id: str | None,
    ) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if title is not None:
            task.title = title
        if priority is not None:
            task.priority = priority
        if goal_id is not None:
            task.goal_id = goal_id or None
        self.save_task(task)
        return task

    def create_goal(self, goal: Goal) -> Goal:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO goals (id,title,status,created_at) VALUES (?,?,?,?)",
                (goal.id, goal.title, goal.status, _dt(goal.created_at)),
            )
        return goal

    def list_goals(self) -> list[Goal]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM goals ORDER BY created_at DESC"
            ).fetchall()
        return [Goal(**dict(row)) for row in rows]

    def update_goal_status(self, goal_id: str, status: str) -> Goal:
        with self.connect() as connection:
            changed = connection.execute(
                "UPDATE goals SET status=? WHERE id=?", (status, goal_id)
            ).rowcount
            row = connection.execute(
                "SELECT * FROM goals WHERE id=?", (goal_id,)
            ).fetchone()
        if not changed or row is None:
            raise KeyError(goal_id)
        return Goal(**dict(row))

    def create_commitment(self, commitment: Commitment) -> Commitment:
        if commitment.task_id and self.get_task(commitment.task_id) is None:
            raise KeyError(commitment.task_id)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO commitments
                (id,task_id,statement,promised_at,due_at,kept) VALUES (?,?,?,?,?,?)""",
                (
                    commitment.id, commitment.task_id, commitment.statement,
                    _dt(commitment.promised_at), _dt(commitment.due_at), None,
                ),
            )
        return commitment

    def list_commitments(self, limit: int = 20) -> list[Commitment]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM commitments ORDER BY promised_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_commitment(row) for row in rows]

    def resolve_commitment(self, commitment_id: str, kept: bool) -> Commitment:
        with self.connect() as connection:
            changed = connection.execute(
                "UPDATE commitments SET kept=? WHERE id=?",
                (int(kept), commitment_id),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM commitments WHERE id=?", (commitment_id,)
            ).fetchone()
        if not changed or row is None:
            raise KeyError(commitment_id)
        return _commitment(row)

    def create_memory(self, memory: Memory) -> Memory:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO memories
                (id,kind,content,importance,confidence,source,expires_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    memory.id, memory.kind, memory.content, memory.importance,
                    memory.confidence, memory.source, _dt(memory.expires_at),
                    _dt(memory.created_at), _dt(memory.updated_at),
                ),
            )
        return memory

    def list_memories(self, include_expired: bool = False) -> list[Memory]:
        query = "SELECT * FROM memories"
        params: tuple[str, ...] = ()
        if not include_expired:
            query += " WHERE expires_at IS NULL OR expires_at > ?"
            params = (_dt(utc_now()) or "",)
        query += " ORDER BY importance DESC, updated_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [Memory(**dict(row)) for row in rows]

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None,
        importance: float | None,
        confidence: float | None,
        expires_at,
    ) -> Memory:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            memory = Memory(**dict(row))
            if content is not None:
                memory.content = content
            if importance is not None:
                memory.importance = importance
            if confidence is not None:
                memory.confidence = confidence
            if expires_at is not None:
                memory.expires_at = expires_at
            memory.updated_at = utc_now()
            connection.execute(
                """UPDATE memories SET content=?,importance=?,confidence=?,
                expires_at=?,updated_at=? WHERE id=?""",
                (
                    memory.content, memory.importance, memory.confidence,
                    _dt(memory.expires_at), _dt(memory.updated_at), memory.id,
                ),
            )
        return memory

    def delete_memory(self, memory_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                "DELETE FROM memories WHERE id=?", (memory_id,)
            ).rowcount
        if not changed:
            raise KeyError(memory_id)

    def archive_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        task.status = TaskStatus.ARCHIVED
        self.save_task(task)
        return task

    def update_task_progress(self, task_id: str, progress: float) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        task.progress = progress
        task.status = (
            TaskStatus.COMPLETED if progress == 1 else TaskStatus.IN_PROGRESS
        )
        self.save_task(task)
        return task

    def start_focus_session(self, session: FocusSession) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE focus_sessions SET status='cancelled', ended_at=? "
                "WHERE status='active'",
                (_dt(utc_now()),),
            )
            connection.execute(
                """INSERT INTO focus_sessions
                (id,task_id,planned_minutes,started_at,ended_at,paused_at,status)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    session.id, session.task_id, session.planned_minutes,
                    _dt(session.started_at), _dt(session.ended_at),
                    _dt(session.paused_at), session.status,
                ),
            )

    def active_focus_session(self) -> FocusSession | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM focus_sessions WHERE status IN ('active','paused') "
                "ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return FocusSession(**dict(row)) if row else None

    def get_focus_session(self, session_id: str) -> FocusSession | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM focus_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return FocusSession(**dict(row)) if row else None

    def save_focus_session(self, session: FocusSession) -> FocusSession:
        with self.connect() as connection:
            connection.execute(
                """UPDATE focus_sessions SET started_at=?, ended_at=?, paused_at=?,
                status=? WHERE id=?""",
                (
                    _dt(session.started_at), _dt(session.ended_at),
                    _dt(session.paused_at), session.status, session.id,
                ),
            )
        return session

    def focus_history(self, limit: int = 10) -> list[FocusSession]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM focus_sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [FocusSession(**dict(row)) for row in rows]

    def record_event(self, session_id: str, event_type: str, payload: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO interaction_events
                (session_id,event_type,payload_json,created_at) VALUES (?,?,?,?)""",
                (session_id, event_type, json.dumps(payload, default=str), _dt(utc_now())),
            )

    def claim_inbound_event(self, event_id: str, session_id: str) -> bool:
        try:
            with self.connect() as connection:
                connection.execute(
                    "INSERT INTO inbound_events (event_id,session_id,created_at) VALUES (?,?,?)",
                    (event_id, session_id, _dt(utc_now())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def record_outbound_envelope(self, envelope: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO outbound_events
                (event_id,session_id,envelope_json,requires_ack,created_at)
                VALUES (?,?,?,?,?)""",
                (
                    envelope["event_id"], envelope["session_id"],
                    json.dumps(envelope, default=str), int(envelope["requires_ack"]),
                    envelope["timestamp"],
                ),
            )

    def acknowledge_outbound_event(
        self, event_id: str, session_id: str, status: str
    ) -> bool:
        with self.connect() as connection:
            if status == "applied":
                changed = connection.execute(
                    """UPDATE outbound_events SET acknowledged_at=?,
                    acknowledgement_status=? WHERE event_id=? AND session_id=?
                    AND acknowledged_at IS NULL""",
                    (_dt(utc_now()), status, event_id, session_id),
                ).rowcount
            else:
                changed = connection.execute(
                    """UPDATE outbound_events SET acknowledgement_status=?
                    WHERE event_id=? AND session_id=? AND acknowledged_at IS NULL""",
                    (status, event_id, session_id),
                ).rowcount
        return bool(changed)

    def pending_outbound_envelopes(self, session_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT envelope_json FROM outbound_events
                WHERE session_id=? AND requires_ack=1 AND acknowledged_at IS NULL
                ORDER BY created_at""",
                (session_id,),
            ).fetchall()
        return [json.loads(row["envelope_json"]) for row in rows]


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _task(row: sqlite3.Row) -> Task:
    return Task(**dict(row))


def _commitment(row: sqlite3.Row) -> Commitment:
    data = dict(row)
    data["kept"] = None if data["kept"] is None else bool(data["kept"])
    return Commitment(**data)
