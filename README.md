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
The v0.1 living portrait maps Mira's structured expression cues to six
consistent character states—neutral, listening, focused, skeptical, warm smile,
and quietly pleased—without requiring Unreal Engine at runtime.
The second dashboard slice adds task editing and archival, Focus pause/resume/
complete/cancel controls, and recent Focus-session history.
The third slice introduces goals, goal-linked tasks, explicit commitments with
due times, and kept/missed outcomes for future evidence-based coaching.

## Reasoning providers

Mira always has a deterministic local fallback. To enable the optional OpenAI
structured-output provider, install `.[ai]`, copy `.env.example` to your local
environment, and set both `OPENAI_API_KEY` and `MIRA_OPENAI_MODEL`. The model
receives task, goal, commitment, Focus, and progress context, but the backend
keeps exclusive authority over UI and persistence actions.

## Controlled memory

Memories are local, visible, correctable, deletable, and optionally expiring.
Each record carries a source, confidence, and importance score. Mira receives at
most five non-expired memories ranked by simple lexical relevance and importance;
the system does not create hidden profiles or require vector storage.

## Conversational follow-up

The dashboard also supports ordinary follow-up conversation over the versioned
WebSocket. Each user/Mira turn is persisted per session, and Mira receives the
12 most recent messages plus optional task, active Focus, and relevant memory
context. Conversation replies deliberately carry no UI actions: tasks,
commitments, memories, and Focus sessions change only through their explicit
commands or the progress check-in.

## Voice adapter

The dashboard uses browser-native streaming speech recognition and speech
synthesis for the first voice vertical slice. It emits provider-neutral voice
lifecycle events over the existing WebSocket and cancels speech immediately
when the microphone starts or the user presses Stop Mira. This adapter is a
prototype boundary that Unreal and production speech providers can replace.

Set `MIRA_OPENAI_STT_MODEL` and/or `MIRA_OPENAI_TTS_MODEL` to enable the
provider-backed adapters. Audio uploads are limited to 10 MB, used in memory for
transcription, and are not persisted. Any provider failure falls back to the
browser adapter; interruption cancels playback and the in-flight audio request.
Speech pauses are cancellable, the portrait exposes preparing/speaking activity,
and interruption clears pending playback before returning Mira to an attentive
state. This prevents delayed audio from starting after the user has said stop.

In a second terminal, run the simulated Unreal client. It deliberately drops
its connection before acknowledging a response, reconnects, verifies the exact
event is replayed, acknowledges it, and exercises voice interruption:

```powershell
.venv\Scripts\python scripts/simulated_unreal_client.py
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

## Versioned WebSocket contract

Every client and server message uses protocol version `0.1` and a stable event
ID. Domain fields live in `payload`, while correlation and delivery metadata
stay in the envelope:

```json
{
  "protocol_version": "0.1",
  "event_id": "unreal-550e8400e29b41d4a716446655440000",
  "session_id": "unreal-sim",
  "type": "progress.reported",
  "timestamp": "2026-08-16T18:00:00Z",
  "correlation_id": null,
  "payload": {
    "source": "voice",
    "task_id": "task-ml",
    "transcript": "I finished the ML assignment.",
    "progress": 1.0
  }
}
```

`mira.response` messages set `requires_ack` to `true`. A client applies the
response and sends `client.ack` with the server event ID and an `applied` or
`failed` status. Unacknowledged responses are stored in SQLite and replayed
with the same event ID when that session reconnects. Client event IDs are also
stored, so retransmitted inputs are identified as duplicates instead of
updating task state twice. Legacy unwrapped client messages remain accepted
during the v0.1 transition.
