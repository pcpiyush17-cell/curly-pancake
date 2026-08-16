from fastapi.testclient import TestClient

from mira.main import create_app
from mira.models import Expression, Gesture, MiraResponse, MiraState
from mira.policy import DeterministicMiraPolicy
from mira.reasoning import DeterministicReasoningProvider, SafeReasoningEngine


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
            thinking = socket.receive_json()
            assert thinking["type"] == "mira.thinking"
            assert thinking["payload"]["task_id"] == "task-ml"
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


def test_goal_and_commitment_lifecycle(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        goal_response = client.post("/api/goals", json={"title": "Ship Mira v0.1"})
        assert goal_response.status_code == 201
        goal = goal_response.json()

        task_response = client.post(
            "/api/tasks",
            json={"title": "Write release checklist", "priority": 1, "goal_id": goal["id"]},
        )
        assert task_response.status_code == 201
        task = task_response.json()
        assert task["goal_id"] == goal["id"]

        commitment_response = client.post(
            "/api/commitments",
            json={
                "statement": "Finish the checklist tonight",
                "task_id": task["id"],
                "due_at": "2026-08-16T22:00:00+05:30",
            },
        )
        assert commitment_response.status_code == 201
        commitment = commitment_response.json()
        assert commitment["kept"] is None

        resolved = client.post(f"/api/commitments/{commitment['id']}/kept")
        assert resolved.status_code == 200
        assert resolved.json()["kept"] is True

        achieved = client.post(f"/api/goals/{goal['id']}/achieved")
        assert achieved.status_code == 200
        assert achieved.json()["status"] == "achieved"

        snapshot = client.get("/api/snapshot").json()
        assert snapshot["goals"][0]["id"] == goal["id"]
        assert snapshot["commitments"][0]["kept"] is True


class StubReasoningProvider:
    name = "stub"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.context = None

    def generate(self, context):
        self.context = context
        if self.fail:
            raise RuntimeError("provider unavailable")
        return MiraResponse(
            speech="You made progress. Now name the part you are avoiding.",
            state=MiraState.CHALLENGING,
            tone="wry",
            tone_intensity=0.55,
            expression=Expression(primary="raised_eyebrow", intensity=0.4),
            gesture=Gesture(type="subtle_head_tilt", intensity=0.25),
            ui_actions=[],
        )


def test_reasoning_provider_gets_context_but_not_action_authority(tmp_path):
    app = create_app(tmp_path / "test.db")
    stub = StubReasoningProvider()
    fallback = DeterministicReasoningProvider(DeterministicMiraPolicy())
    app.state.service.reasoning = SafeReasoningEngine(stub, fallback)
    with TestClient(app) as client:
        client.post("/api/goals", json={"title": "Ship Mira"})
        client.post(
            "/api/commitments",
            json={"statement": "Finish ML today", "task_id": "task-ml"},
        )
        response = client.post(
            "/api/progress",
            json={
                "source": "text",
                "task_id": "task-ml",
                "transcript": "I made some progress.",
                "progress": 0.5,
            },
        ).json()

        assert response["speech"].startswith("You made progress")
        assert response["ui_actions"][0]["type"] == "update_task"
        assert len(stub.context.goals) == 1
        assert len(stub.context.commitments) == 1


def test_reasoning_provider_failure_uses_deterministic_fallback(tmp_path):
    app = create_app(tmp_path / "test.db")
    stub = StubReasoningProvider(fail=True)
    fallback = DeterministicReasoningProvider(DeterministicMiraPolicy())
    app.state.service.reasoning = SafeReasoningEngine(stub, fallback)
    with TestClient(app) as client:
        response = client.post(
            "/api/progress",
            json={
                "source": "text",
                "task_id": "task-ml",
                "transcript": "Nothing moved.",
                "progress": 0,
            },
        )
        assert response.status_code == 200
        assert response.json()["state"] == "CHALLENGING"
        status = client.get("/api/reasoning/status").json()
        assert status["last_provider"] == "deterministic"
        assert status["last_error"]["type"] == "RuntimeError"
        assert status["last_error"]["status_code"] is None


def test_persona_instructions_enforce_concise_user_facing_speech():
    from mira.reasoning import PERSONA_INSTRUCTIONS

    normalized = " ".join(PERSONA_INSTRUCTIONS.split())
    assert "at most two short sentences" in normalized
    assert "Never expose internal task IDs" in normalized
    assert 'phrase "transcript"' in normalized


def test_user_controlled_memory_lifecycle_and_retrieval(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        created = client.post(
            "/api/memories",
            json={
                "kind": "preference",
                "content": "I focus better on DSA before checking messages",
                "importance": 0.8,
                "confidence": 1,
            },
        )
        assert created.status_code == 201
        memory = created.json()
        assert memory["source"] == "user"

        corrected = client.patch(
            f"/api/memories/{memory['id']}",
            json={"content": "I focus better before checking messages"},
        )
        assert corrected.status_code == 200
        assert corrected.json()["content"] == "I focus better before checking messages"

        relevant = app.state.service.relevant_memories("starting focused work")
        assert relevant[0].id == memory["id"]
        assert client.get("/api/snapshot").json()["memories"][0]["id"] == memory["id"]

        deleted = client.delete(f"/api/memories/{memory['id']}")
        assert deleted.status_code == 204
        assert client.get("/api/snapshot").json()["memories"] == []


def test_expired_memory_is_not_retrieved(tmp_path):
    app = create_app(tmp_path / "test.db")
    with TestClient(app) as client:
        created = client.post(
            "/api/memories",
            json={
                "kind": "reflection",
                "content": "Temporary DSA blocker",
                "importance": 1,
                "expires_at": "2020-01-01T00:00:00Z",
            },
        )
        assert created.status_code == 201
        assert app.state.service.relevant_memories("DSA blocker") == []
        assert client.get("/api/snapshot").json()["memories"] == []
