from fastapi.testclient import TestClient

from mira.main import create_app


def test_progress_focus_vertical_slice(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/session/test-session") as socket:
            ready = socket.receive_json()
            assert ready["type"] == "session.ready"

            socket.send_json(
                {
                    "type": "progress.reported",
                    "source": "voice",
                    "task_id": "task-ml",
                    "transcript": "Finished ML. Start a DSA focus session.",
                    "progress": 1,
                    "start_focus": True,
                    "focus_task_id": "task-dsa",
                    "focus_minutes": 25,
                }
            )
            message = socket.receive_json()

            assert message["type"] == "mira.response"
            response = message["payload"]
            assert response["state"] == "FOCUSING"
            assert response["tone"] == "focused"
            assert [action["type"] for action in response["ui_actions"]] == [
                "update_task",
                "highlight_task",
                "start_focus_mode",
            ]

            socket.send_json({"type": "session.snapshot.requested"})
            snapshot = socket.receive_json()["payload"]
            task = next(task for task in snapshot["tasks"] if task["id"] == "task-ml")
            assert task["status"] == "completed"
            assert task["progress"] == 1
            assert snapshot["active_focus_session"]["task_id"] == "task-dsa"


def test_zero_progress_uses_challenger_voice(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.post(
            "/api/progress",
            json={
                "source": "text",
                "task_id": "task-ml",
                "transcript": "I did not start.",
                "progress": 0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "CHALLENGING"
        assert body["speech"] == "Okay. What actually got in the way?"


def test_unknown_task_returns_404(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        response = client.post(
            "/api/progress",
            json={
                "source": "text",
                "task_id": "missing",
                "transcript": "Done.",
                "progress": 1,
            },
        )
        assert response.status_code == 404

