from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from mira.db import SQLiteRepository
from mira.models import (
    ClientEvent,
    CommitmentCreate,
    GoalCreate,
    MemoryCreate,
    MemoryUpdate,
    ProgressReported,
    SnapshotRequested,
    TaskCreate,
    TaskUpdate,
    VoiceLifecycleEvent,
)
from mira.policy import DeterministicMiraPolicy
from mira.service import MiraService


def create_app(database_path: str | Path | None = None) -> FastAPI:
    db_path = database_path or os.getenv("MIRA_DB_PATH", "mira.db")
    repository = SQLiteRepository(db_path)
    service = MiraService(repository, DeterministicMiraPolicy())
    event_adapter = TypeAdapter(ClientEvent)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        repository.seed_demo_tasks()
        yield

    app = FastAPI(title="Mira v0.1", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(web_dir / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/reasoning/status")
    def reasoning_status():
        return {
            "configured_provider": service.reasoning.configured_provider,
            "last_provider": service.reasoning.last_provider,
            "last_error": service.reasoning.last_error,
        }

    @app.get("/api/snapshot")
    def snapshot():
        return service.snapshot()

    @app.post("/api/tasks", status_code=201)
    def create_task(task: TaskCreate):
        return service.create_task(task)

    @app.post("/api/goals", status_code=201)
    def create_goal(goal: GoalCreate):
        return service.create_goal(goal)

    @app.post("/api/goals/{goal_id}/{status}")
    def update_goal_status(goal_id: str, status: str):
        if status not in {"active", "achieved", "paused"}:
            raise HTTPException(status_code=404, detail="Unknown goal status")
        try:
            return service.update_goal_status(goal_id, status)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown goal")

    @app.post("/api/commitments", status_code=201)
    def create_commitment(commitment: CommitmentCreate):
        try:
            return service.create_commitment(commitment)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown task")

    @app.post("/api/commitments/{commitment_id}/{result}")
    def resolve_commitment(commitment_id: str, result: str):
        if result not in {"kept", "missed"}:
            raise HTTPException(status_code=404, detail="Unknown commitment result")
        try:
            return service.resolve_commitment(commitment_id, result == "kept")
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown commitment")

    @app.post("/api/memories", status_code=201)
    def create_memory(memory: MemoryCreate):
        return service.create_memory(memory)

    @app.patch("/api/memories/{memory_id}")
    def update_memory(memory_id: str, memory: MemoryUpdate):
        try:
            return service.update_memory(memory_id, memory)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown memory")

    @app.delete("/api/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: str):
        try:
            service.delete_memory(memory_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown memory")

    @app.patch("/api/tasks/{task_id}")
    def update_task(task_id: str, task: TaskUpdate):
        try:
            return service.update_task(task_id, task)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")

    @app.post("/api/tasks/{task_id}/archive")
    def archive_task(task_id: str):
        try:
            return service.archive_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}")
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @app.post("/api/focus/{session_id}/{action}")
    def transition_focus(session_id: str, action: str):
        if action not in {"pause", "resume", "complete", "cancel"}:
            raise HTTPException(status_code=404, detail="Unknown Focus action")
        try:
            return service.transition_focus(session_id, action)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown Focus session")
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @app.post("/api/progress")
    def report_progress(event: ProgressReported):
        try:
            return service.report_progress("http", event)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown task: {error.args[0]}")

    @app.websocket("/ws/session/{session_id}")
    async def session(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        await websocket.send_json(
            {"type": "session.ready", "payload": service.snapshot().model_dump(mode="json")}
        )
        try:
            while True:
                raw_event = await websocket.receive_json()
                try:
                    event = event_adapter.validate_python(raw_event)
                    if isinstance(event, ProgressReported):
                        await websocket.send_json(
                            {
                                "type": "mira.thinking",
                                "payload": {"task_id": event.task_id},
                            }
                        )
                        response = await asyncio.to_thread(
                            service.report_progress, session_id, event
                        )
                        await websocket.send_json(
                            {
                                "type": "mira.response",
                                "payload": response.model_dump(mode="json"),
                            }
                        )
                    elif isinstance(event, SnapshotRequested):
                        await websocket.send_json(
                            {
                                "type": "session.snapshot",
                                "payload": service.snapshot().model_dump(mode="json"),
                            }
                        )
                    elif isinstance(event, VoiceLifecycleEvent):
                        service.record_voice_event(session_id, event)
                        await websocket.send_json(
                            {
                                "type": "voice.event.recorded",
                                "payload": {"event_type": event.type},
                            }
                        )
                except KeyError as error:
                    await websocket.send_json(
                        {"type": "error", "code": "task_not_found", "detail": error.args[0]}
                    )
                except ValidationError as error:
                    await websocket.send_json(
                        {"type": "error", "code": "invalid_event", "detail": error.errors()}
                    )
        except WebSocketDisconnect:
            return

    return app


app = create_app()
