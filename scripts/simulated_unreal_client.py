"""Exercise Mira's reliable WebSocket contract as a simulated Unreal client."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

from websockets.asyncio.client import connect


URL = os.getenv("MIRA_WS_URL", "ws://127.0.0.1:8000/ws/session/unreal-sim")


def client_event(event_type: str, payload: dict, correlation_id: str | None = None) -> str:
    return json.dumps(
        {
            "protocol_version": "0.1",
            "event_id": f"unreal-{uuid4().hex}",
            "session_id": "unreal-sim",
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "correlation_id": correlation_id,
            "payload": payload,
        }
    )


async def receive_type(socket, wanted: str) -> dict:
    while True:
        event = json.loads(await socket.recv())
        print(f"<- {event['type']} [{event['event_id']}]")
        if event["type"] == wanted:
            return event


async def acknowledge(socket, event: dict) -> None:
    await socket.send(
        client_event(
            "client.ack",
            {"event_id": event["event_id"], "status": "applied"},
            event["event_id"],
        )
    )
    recorded = await receive_type(socket, "client.ack.recorded")
    print(f"   acknowledged={recorded['payload']['recorded']}")


async def main() -> None:
    print("1. Connecting as the Unreal simulator")
    async with connect(URL) as socket:
        await receive_type(socket, "session.ready")
        await socket.send(
            client_event(
                "progress.reported",
                {
                    "source": "voice",
                    "task_id": "task-ml",
                    "transcript": "I finished the ML assignment. Start DSA focus mode.",
                    "progress": 1.0,
                    "start_focus": True,
                    "focus_task_id": "task-dsa",
                    "focus_minutes": 25,
                },
            )
        )
        await receive_type(socket, "mira.thinking")
        response = await receive_type(socket, "mira.response")
        body = response["payload"]
        print(f"   Mira: {body['speech']}")
        print(f"   Avatar: {body['state']} / {body['tone']}")
        print(f"   Expression: {body['expression']['primary']}")
        print(f"   UI actions: {[action['type'] for action in body['ui_actions']]}")
        response_id = response["event_id"]
        print("2. Simulating a network drop before the response ACK")

    print("3. Reconnecting with the same session ID")
    async with connect(URL) as socket:
        await receive_type(socket, "session.ready")
        replay = await receive_type(socket, "mira.response")
        assert replay["event_id"] == response_id, "Server did not replay the same event"
        print("   Exact pending response replayed safely")
        await acknowledge(socket, replay)
        await socket.send(client_event("user.speech.started", {"transcript": None}))
        await receive_type(socket, "voice.event.recorded")
        await socket.send(client_event("mira.speech.interrupted", {"transcript": None}))
        await receive_type(socket, "voice.event.recorded")
        print("4. Voice lifecycle and immediate interruption recorded")


if __name__ == "__main__":
    asyncio.run(main())
