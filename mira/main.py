from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from mira.db import SQLiteRepository
from mira.models import (
    ClientAck,
    ClientEnvelope,
    ClientEvent,
    ConversationMessageSent,
    CommitmentCreate,
    GoalCreate,
    MemoryCreate,
    MemoryUpdate,
    ProgressReported,
    SnapshotRequested,
    SpeechRequest,
    TaskCreate,
    TaskUpdate,
    VoiceLifecycleEvent,
)
from mira.policy import DeterministicMiraPolicy
from mira.protocol import make_server_envelope
from mira.service import MiraService
from mira.speech import build_speech_provider


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
    app.state.repository = repository
    app.state.speech = build_speech_provider()
    app.state.last_voice_error = None
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

    @app.get("/api/voice/status")
    def voice_status():
        provider = app.state.speech
        return {
            "provider": provider.name,
            "transcription_enabled": provider.transcription_enabled,
            "synthesis_enabled": provider.synthesis_enabled,
            "last_error": app.state.last_voice_error,
        }

    @app.get("/api/desktop/status")
    def desktop_status():
        import importlib.util

        from mira.desktop import is_startup_enabled

        return {
            "windows": os.name == "nt",
            "tray_available": bool(
                importlib.util.find_spec("pystray")
                and importlib.util.find_spec("PIL")
            ),
            "startup_enabled": is_startup_enabled(),
        }

    @app.post("/api/desktop/startup/{enabled}")
    def update_desktop_startup(enabled: bool):
        from mira.desktop import set_startup_enabled

        try:
            return {"startup_enabled": set_startup_enabled(enabled)}
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error))

    @app.post("/api/voice/transcribe")
    async def transcribe_voice(request: Request):
        provider = app.state.speech
        if not provider.transcription_enabled:
            raise HTTPException(status_code=503, detail="Server transcription unavailable")
        audio = await request.body()
        if not audio:
            raise HTTPException(status_code=422, detail="Audio is required")
        if len(audio) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Audio exceeds 10 MB")
        content_type = request.headers.get("content-type", "audio/webm")
        try:
            text = await asyncio.to_thread(provider.transcribe, audio, content_type)
            app.state.last_voice_error = None
        except Exception as error:
            status_code = getattr(error, "status_code", None)
            raw_code = getattr(error, "code", None)
            code = str(raw_code) if raw_code is not None else None
            if status_code == 401:
                message = "OpenAI rejected the API key"
            elif status_code == 429:
                message = "OpenAI transcription quota or rate limit was reached"
            elif status_code in {400, 415, 422}:
                message = "OpenAI rejected the recorded audio format"
            elif status_code == 404:
                message = "The configured transcription model is unavailable"
            else:
                message = "Could not connect to OpenAI transcription"
            app.state.last_voice_error = {
                "type": type(error).__name__,
                "status_code": status_code,
                "code": code,
                "message": message,
            }
            raise HTTPException(status_code=502, detail=app.state.last_voice_error)
        return {"text": text}

    @app.post("/api/voice/speak")
    async def synthesize_voice(speech: SpeechRequest):
        provider = app.state.speech
        if not provider.synthesis_enabled:
            raise HTTPException(status_code=503, detail="Server speech unavailable")
        try:
            audio = await asyncio.to_thread(provider.synthesize, speech.text)
        except Exception:
            raise HTTPException(status_code=502, detail="Speech provider failed")
        return Response(content=audio, media_type="audio/mpeg")

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
        async def send_event(
            event_type: str,
            payload: dict,
            *,
            requires_ack: bool = False,
            correlation_id: str | None = None,
        ):
            envelope = make_server_envelope(
                session_id=session_id,
                event_type=event_type,
                payload=payload,
                requires_ack=requires_ack,
                correlation_id=correlation_id,
            )
            data = envelope.model_dump(mode="json")
            if requires_ack:
                repository.record_outbound_envelope(data)
            await websocket.send_json(data)
            return envelope

        await websocket.accept()
        await send_event(
            "session.ready", service.snapshot(session_id).model_dump(mode="json")
        )
        for pending in repository.pending_outbound_envelopes(session_id):
            await websocket.send_json(pending)
        try:
            while True:
                raw_event = await websocket.receive_json()
                try:
                    correlation_id = None
                    if "protocol_version" in raw_event:
                        client_envelope = ClientEnvelope.model_validate(raw_event)
                        if client_envelope.session_id != session_id:
                            await send_event(
                                "error",
                                {"code": "session_mismatch", "detail": "Session ID mismatch"},
                                correlation_id=client_envelope.event_id,
                            )
                            continue
                        correlation_id = (
                            client_envelope.correlation_id or client_envelope.event_id
                        )
                        if client_envelope.type == "client.ack":
                            ack = ClientAck.model_validate(client_envelope.payload)
                            recorded = repository.acknowledge_outbound_event(
                                ack.event_id, session_id, ack.status
                            )
                            await send_event(
                                "client.ack.recorded",
                                {"event_id": ack.event_id, "recorded": recorded},
                                correlation_id=correlation_id,
                            )
                            continue
                        if not repository.claim_inbound_event(
                            client_envelope.event_id, session_id
                        ):
                            await send_event(
                                "client.duplicate",
                                {"event_id": client_envelope.event_id, "ignored": True},
                                correlation_id=correlation_id,
                            )
                            continue
                        raw_event = {
                            "type": client_envelope.type,
                            **client_envelope.payload,
                        }
                    event = event_adapter.validate_python(raw_event)
                    if isinstance(event, ProgressReported):
                        await send_event(
                            "mira.thinking",
                            {"task_id": event.task_id},
                            correlation_id=correlation_id,
                        )
                        response = await asyncio.to_thread(
                            service.report_progress, session_id, event
                        )
                        await send_event(
                            "mira.response",
                            response.model_dump(mode="json"),
                            requires_ack=True,
                            correlation_id=correlation_id,
                        )
                    elif isinstance(event, ConversationMessageSent):
                        await send_event(
                            "mira.thinking",
                            {"task_id": event.task_id},
                            correlation_id=correlation_id,
                        )
                        turn = await asyncio.to_thread(
                            service.converse, session_id, event
                        )
                        await send_event(
                            "conversation.turn",
                            turn.model_dump(mode="json"),
                            requires_ack=True,
                            correlation_id=correlation_id,
                        )
                    elif isinstance(event, SnapshotRequested):
                        await send_event(
                            "session.snapshot",
                            service.snapshot(session_id).model_dump(mode="json"),
                            correlation_id=correlation_id,
                        )
                    elif isinstance(event, VoiceLifecycleEvent):
                        service.record_voice_event(session_id, event)
                        await send_event(
                            "voice.event.recorded",
                            {"event_type": event.type},
                            correlation_id=correlation_id,
                        )
                except KeyError as error:
                    await send_event(
                        "error",
                        {"code": "task_not_found", "detail": error.args[0]},
                        correlation_id=correlation_id,
                    )
                except ValidationError as error:
                    await send_event(
                        "error",
                        {"code": "invalid_event", "detail": error.errors()},
                        correlation_id=correlation_id,
                    )
        except WebSocketDisconnect:
            return

    return app


app = create_app()
