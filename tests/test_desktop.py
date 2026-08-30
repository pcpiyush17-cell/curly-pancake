import os
from datetime import UTC, datetime, timedelta

from mira import desktop


def test_dashboard_url_uses_loopback_for_wildcard_host():
    assert desktop.dashboard_url("0.0.0.0", 8123) == "http://127.0.0.1:8123/"
    assert desktop.dashboard_url("127.0.0.1", 8000) == "http://127.0.0.1:8000/"


def test_local_server_reuses_existing_healthy_service(monkeypatch):
    monkeypatch.setattr(desktop, "is_mira_healthy", lambda host, port: True)
    server = desktop.LocalMiraServer("127.0.0.1", 8000)

    server.start()
    server.stop()

    assert server.owned is False
    assert server.thread is None


def test_wait_until_healthy_retries_until_ready(monkeypatch):
    attempts = iter([False, False, True])
    monkeypatch.setattr(
        desktop, "is_mira_healthy", lambda host, port: next(attempts)
    )
    monkeypatch.setattr(desktop.time, "sleep", lambda interval: None)

    desktop.wait_until_healthy("127.0.0.1", 8000, timeout=1)


def test_local_env_loads_values_without_overwriting_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nMIRA_TEST_NEW="new value"\nMIRA_TEST_KEPT=from-file\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("MIRA_TEST_NEW", raising=False)
    monkeypatch.setenv("MIRA_TEST_KEPT", "already-set")

    desktop.load_local_env(env_file)

    assert os.environ["MIRA_TEST_NEW"] == "new value"
    assert os.environ["MIRA_TEST_KEPT"] == "already-set"


class FakeTrayIcon:
    def __init__(self):
        self.notifications = []

    def notify(self, message, title):
        self.notifications.append((title, message))


def test_tray_notifies_once_for_focus_and_due_commitment():
    tray = desktop.DesktopTray.__new__(desktop.DesktopTray)
    tray.icon = FakeTrayIcon()
    tray.notified_focus = set()
    tray.notified_commitments = set()
    tray.notified_rhythm = set()
    now = datetime.now(UTC)
    snapshot = {
        "tasks": [{"id": "task-1", "title": "Practice DSA"}],
        "active_focus_session": {
            "id": "focus-1", "task_id": "task-1", "status": "active",
            "planned_minutes": 25,
            "started_at": (now - timedelta(minutes=26)).isoformat(),
        },
        "commitments": [{
            "id": "commitment-1", "statement": "Finish the review",
            "due_at": (now - timedelta(minutes=1)).isoformat(), "kept": None,
        }],
        "daily_rhythm": {"enabled": False},
    }

    tray.notify_due_items(snapshot, now)
    tray.notify_due_items(snapshot, now)

    assert tray.icon.notifications == [
        ("Focus complete", "Your focus block for Practice DSA is complete."),
        ("Commitment due", "Finish the review"),
    ]


def test_daily_rhythm_notifies_each_phase_once_per_day():
    tray = desktop.DesktopTray.__new__(desktop.DesktopTray)
    tray.icon = FakeTrayIcon()
    tray.notified_focus = set()
    tray.notified_commitments = set()
    tray.notified_rhythm = set()
    now = datetime.now().astimezone().replace(hour=9, minute=0)
    snapshot = {
        "tasks": [], "commitments": [], "active_focus_session": None,
        "daily_rhythm": {
            "enabled": True, "morning_time": "08:30",
            "midday_time": "13:00", "evening_time": "20:30",
        },
    }

    tray.notify_due_items(snapshot, now)
    tray.notify_due_items(snapshot, now.replace(hour=14))
    tray.notify_due_items(snapshot, now.replace(hour=21))
    tray.notify_due_items(snapshot, now.replace(hour=21))

    assert tray.icon.notifications == [
        ("Morning plan", "Choose today's priorities with Mira."),
        ("Midday check-in", "What moved-and what needs an honest adjustment?"),
        ("Evening review", "Close the loop on today and set up tomorrow."),
    ]


def test_startup_command_uses_background_python():
    command = desktop.startup_command()
    assert "pythonw.exe" in command
    assert command.endswith("-m mira.desktop")

