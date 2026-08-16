# Mira v0.1

Mira is a desktop AI execution companion: a warm mentor who can become a concise, witty challenger when the user's actions and commitments diverge. This repository contains the first backend vertical slice and a mocked client standing in for voice input and the Unreal avatar/UI.

## Vertical slice

1. The client sends a voice transcript or typed progress report over WebSocket.
2. The application service updates the task in SQLite.
3. The current deterministic Mira policy returns a structured `MiraResponse`.
4. The response includes speech, conversational state, tone, avatar direction, and UI actions.
5. A completed task can trigger a persisted Focus Mode session for the next task.

The deterministic policy is intentional. It makes the contract testable before an LLM, speech stack, or Unreal client is connected.

## Run

Create an environment and install the project with its development dependencies:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Start the API:

```powershell
.venv\Scripts\python -m uvicorn mira.main:app --reload
```

Open `http://127.0.0.1:8000` for the local execution dashboard. It supports
task creation, progress check-ins, live structured Mira responses, persisted
task state, and a visible Focus Mode timer.
The second dashboard slice adds task editing and archival, Focus pause/resume/
complete/cancel controls, and recent Focus-session history.

In a second terminal, run the mock end-to-end interaction:

```powershell
.venv\Scripts\python scripts/mock_vertical_slice.py
```

HTTP documentation is available at `http://127.0.0.1:8000/docs`. The live client endpoint is `ws://127.0.0.1:8000/ws/session/{session_id}`.

## Architecture

```text
Unreal / MetaHuman-style client (later)     Mock client (now)
                 \                              /
                  WebSocket JSON event contract
                              |
                       FastAPI transport
                              |
                     Mira application service
                       /                  \
          deterministic response policy   SQLite repository
                     (LLM later)       tasks, goals, commitments,
                                       memories, focus sessions
```

Core rules:

- Transport models do not contain persistence logic.
- The response policy does not know about FastAPI or SQLite.
- UI and avatar clients act only on structured response fields.
- No romantic or dependency-forming behavior belongs in Mira's persona.
- No multi-agent framework is used.

## Current event contract

Client progress event:

```json
{
  "type": "progress.reported",
  "source": "voice",
  "task_id": "task-ml",
  "transcript": "I finished the ML assignment. Start focus mode for DSA.",
  "progress": 1.0,
  "start_focus": true,
  "focus_task_id": "task-dsa",
  "focus_minutes": 25
}
```

The server responds with `type: "mira.response"` and a structured `MiraResponse`. Send `type: "session.snapshot.requested"` to retrieve the persisted task and active Focus Mode state.
