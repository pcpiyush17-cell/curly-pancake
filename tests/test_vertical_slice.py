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


def test_dashboard_and_task_creation(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Make the next move real" in dashboard.text
        assert client.get("/static/app.js").status_code == 200

        created = client.post(
            "/api/tasks", json={"title": "Wire the Unreal client", "priority": 2}
        )
        assert created.status_code == 201
        task = created.json()
        assert task["title"] == "Wire the Unreal client"
        assert task["status"] == "todo"

        snapshot = client.get("/api/snapshot").json()
        assert any(item["id"] == task["id"] for item in snapshot["tasks"])

        blank = client.post("/api/tasks", json={"title": "   ", "priority": 3})
        assert blank.status_code == 422


def test_task_edit_and_archive(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        updated = client.patch(
            "/api/tasks/task-ml", json={"title": "Finish ML review", "priority": 2}
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Finish ML review"
        assert updated.json()["priority"] == 2

        archived = client.post("/api/tasks/task-ml/archive")
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"
        ids = {task["id"] for task in client.get("/api/snapshot").json()["tasks"]}
        assert "task-ml" not in ids


def test_focus_lifecycle_and_history(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        started = client.post(
            "/api/progress",
            json={
                "source": "text",
                "task_id": "task-ml",
                "transcript": "ML is done. Starting DSA.",
                "progress": 1,
                "start_focus": True,
                "focus_task_id": "task-dsa",
                "focus_minutes": 25,
            },
        ).json()
        focus_id = next(
            action["focus_session_id"]
            for action in started["ui_actions"]
            if action["type"] == "start_focus_mode"
        )

        paused = client.post(f"/api/focus/{focus_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert client.post(f"/api/focus/{focus_id}/pause").status_code == 409

        resumed = client.post(f"/api/focus/{focus_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "active"

        completed = client.post(f"/api/focus/{focus_id}/complete")
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        snapshot = client.get("/api/snapshot").json()
        assert snapshot["active_focus_session"] is None
        assert snapshot["focus_history"][0]["id"] == focus_id
        assert snapshot["focus_history"][0]["status"] == "completed"
