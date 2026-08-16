from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from mira.db import SQLiteRepository
from mira.models import ClientEvent, ProgressReported, SnapshotRequested
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

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/snapshot")
    def snapshot():
        return service.snapshot()

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
                        response = service.report_progress(session_id, event)
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

