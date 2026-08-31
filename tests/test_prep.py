from fastapi.testclient import TestClient

from mira.main import create_app


def test_prep_plan_has_twelve_weeks_and_240_hours(tmp_path):
    app = create_app(tmp_path / "prep.db")
    with TestClient(app) as client:
        plan = client.get("/api/prep").json()
        assert len(plan["weeks"]) == 12
        assert sum(item["planned_minutes"] for week in plan["weeks"] for item in week["items"]) == 14400
        assert plan["current_week"] == 1
        first = plan["weeks"][0]["items"][0]
        assert len(first["actions"]) == 3
        assert first["deliverable"]
        assert first["done_when"]


def test_prep_item_can_be_queued_and_completed(tmp_path):
    app = create_app(tmp_path / "prep.db")
    with TestClient(app) as client:
        queued = client.post("/api/prep/items/prep-w01-dsa/queue")
        assert queued.status_code == 200
        payload = queued.json()
        assert payload["item"]["status"] == "in_progress"
        assert payload["item"]["task_id"] == payload["task"]["id"]
        tasks = client.get("/api/snapshot").json()["tasks"]
        assert any(task["id"] == payload["task"]["id"] for task in tasks)

        completed = client.patch(
            "/api/prep/items/prep-w01-dsa", json={"status": "completed"}
        )
        assert completed.status_code == 200
        plan = client.get("/api/prep").json()
        assert plan["completed_minutes"] == 480


def test_queue_is_idempotent(tmp_path):
    app = create_app(tmp_path / "prep.db")
    with TestClient(app) as client:
        first = client.post("/api/prep/items/prep-w01-review/queue").json()
        second = client.post("/api/prep/items/prep-w01-review/queue").json()
        assert first["task"]["id"] == second["task"]["id"]


def test_persisted_status_keeps_canonical_action_details(tmp_path):
    app = create_app(tmp_path / "prep.db")
    with TestClient(app) as client:
        client.post("/api/prep/items/prep-w01-fundamentals/queue")
        item = next(
            item
            for week in client.get("/api/prep").json()["weeks"]
            for item in week["items"]
            if item["id"] == "prep-w01-fundamentals"
        )
        assert item["status"] == "in_progress"
        assert item["task_id"]
        assert item["actions"]
        assert "TAAI" in item["actions"][0]
