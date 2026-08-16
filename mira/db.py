from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from mira.models import FocusSession, Task, TaskStatus, utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL CHECK(progress >= 0 AND progress <= 1),
    priority INTEGER NOT NULL,
    due_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
    importance REAL NOT NULL, created_at TEXT NOT NULL
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
                (id,title,status,progress,priority,due_at,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                status=excluded.status, progress=excluded.progress,
                priority=excluded.priority, due_at=excluded.due_at,
                updated_at=excluded.updated_at""",
                (
                    task.id, task.title, task.status.value, task.progress,
                    task.priority, _dt(task.due_at), _dt(task.created_at),
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

    def update_task(self, task_id: str, *, title: str | None, priority: int | None) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if title is not None:
            task.title = title
        if priority is not None:
            task.priority = priority
        self.save_task(task)
        return task

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


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _task(row: sqlite3.Row) -> Task:
    return Task(**dict(row))
