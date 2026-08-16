"""Mock the Unreal/voice client against a running Mira server."""

import asyncio
import json

from websockets.asyncio.client import connect


async def main() -> None:
    async with connect("ws://127.0.0.1:8000/ws/session/demo") as socket:
        print(json.dumps(json.loads(await socket.recv()), indent=2))
        await socket.send(
            json.dumps(
                {
                    "type": "progress.reported",
                    "source": "voice",
                    "task_id": "task-ml",
                    "transcript": "I finished the ML assignment. Start focus mode for DSA.",
                    "progress": 1.0,
                    "start_focus": True,
                    "focus_task_id": "task-dsa",
                    "focus_minutes": 25,
                }
            )
        )
        print(json.dumps(json.loads(await socket.recv()), indent=2))
        await socket.send(json.dumps({"type": "session.snapshot.requested"}))
        print(json.dumps(json.loads(await socket.recv()), indent=2))


if __name__ == "__main__":
    asyncio.run(main())

