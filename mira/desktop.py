from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def dashboard_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}/"


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def open_app_window(url: str) -> None:
    try:
        import webview
    except ImportError as error:
        raise RuntimeError(
            "The lightweight desktop window is not installed yet.\n\n"
            'Run this once in F:\\Mira:\n.venv\\Scripts\\python -m pip install "pywebview>=5.4,<7"'
        ) from error

    window = webview.create_window(
        "Mira - Execution Companion",
        url,
        width=1440,
        height=900,
        min_size=(960, 680),
        background_color="#0d1111",
    )
    tray = DesktopTray(window, url)
    if tray.available:
        window.events.closing += tray.on_window_closing
        tray.start()
    try:
        webview.start(debug=os.getenv("MIRA_DESKTOP_DEBUG") == "1")
    finally:
        tray.stop()


class DesktopTray:
    def __init__(self, window, url: str) -> None:
        self.window = window
        self.url = url.rstrip("/")
        self.icon = None
        self.quitting = False
        self.stop_event = threading.Event()
        self.notified_focus: set[str] = set()
        self.notified_commitments: set[str] = set()
        self.notified_rhythm: set[str] = set()
        try:
            import pystray
            from PIL import Image

            image = Image.open(
                PROJECT_ROOT / "mira/web/assets/avatar/mira-neutral.png"
            ).convert("RGB")
            image.thumbnail((128, 128))
            menu = pystray.Menu(
                pystray.MenuItem("Open Mira", self.show_window, default=True),
                pystray.MenuItem("Quit Mira", self.quit),
            )
            self.icon = pystray.Icon("mira", image, "Mira", menu)
        except ImportError:
            self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def start(self) -> None:
        if not self.icon:
            return
        self.icon.run_detached()
        threading.Thread(
            target=self.monitor, name="mira-desktop-monitor", daemon=True
        ).start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.icon:
            self.icon.stop()

    def on_window_closing(self) -> bool:
        if self.quitting:
            return True
        self.window.hide()
        if self.icon:
            self.icon.notify("Mira is still running here.", "Mira")
        return False

    def show_window(self, *_args) -> None:
        self.window.show()

    def quit(self, *_args) -> None:
        self.quitting = True
        self.stop_event.set()
        if self.icon:
            self.icon.stop()
        self.window.destroy()

    def fetch_snapshot(self) -> dict | None:
        try:
            with urlopen(f"{self.url}/api/snapshot", timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return None

    def monitor(self) -> None:
        while not self.stop_event.wait(5):
            snapshot = self.fetch_snapshot()
            if snapshot:
                self.notify_due_items(snapshot)

    def notify_due_items(self, snapshot: dict, now: datetime | None = None) -> None:
        if not self.icon:
            return
        now = now or datetime.now(UTC)
        focus = snapshot.get("active_focus_session")
        if focus and focus.get("status") == "active":
            started = datetime.fromisoformat(focus["started_at"].replace("Z", "+00:00"))
            elapsed = (now - started).total_seconds()
            if elapsed >= focus["planned_minutes"] * 60 and focus["id"] not in self.notified_focus:
                self.notified_focus.add(focus["id"])
                task = next((item for item in snapshot.get("tasks", []) if item["id"] == focus["task_id"]), None)
                title = task["title"] if task else "your task"
                self.icon.notify(f"Your focus block for {title} is complete.", "Focus complete")
        for commitment in snapshot.get("commitments", []):
            due_at = commitment.get("due_at")
            if commitment.get("kept") is not None or not due_at or commitment["id"] in self.notified_commitments:
                continue
            due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            if due <= now:
                self.notified_commitments.add(commitment["id"])
                self.icon.notify(commitment["statement"], "Commitment due")
        rhythm = snapshot.get("daily_rhythm") or {}
        if not rhythm.get("enabled"):
            return
        local_now = now.astimezone()
        current = local_now.strftime("%H:%M")
        date_key = local_now.date().isoformat()
        check_ins = (
            ("morning", rhythm.get("morning_time"), "Morning plan", "Choose today's priorities with Mira."),
            ("midday", rhythm.get("midday_time"), "Midday check-in", "What moved-and what needs an honest adjustment?"),
            ("evening", rhythm.get("evening_time"), "Evening review", "Close the loop on today and set up tomorrow."),
        )
        due = [item for item in check_ins if item[1] and current >= item[1]]
        if due:
            phase, _scheduled, title, message = due[-1]
            key = f"{date_key}:{phase}"
            if key not in self.notified_rhythm:
                self.notified_rhythm.add(key)
                self.icon.notify(message, title)


def startup_command() -> str:
    pythonw = PROJECT_ROOT / ".venv/Scripts/pythonw.exe"
    return f'"{pythonw}" -m mira.desktop'


def is_startup_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            value, _ = winreg.QueryValueEx(key, "Mira")
            return value == startup_command()
    except FileNotFoundError:
        return False


def set_startup_enabled(enabled: bool) -> bool:
    if os.name != "nt":
        raise RuntimeError("Windows startup is only available on Windows")
    import winreg

    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        if enabled:
            winreg.SetValueEx(key, "Mira", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "Mira")
            except FileNotFoundError:
                pass
    return is_startup_enabled()


def is_mira_healthy(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with urlopen(health_url(host, port), timeout=timeout) as response:
            return (
                response.status == 200
                and json.loads(response.read().decode("utf-8")) == {"status": "ok"}
            )
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def wait_until_healthy(
    host: str, port: int, timeout: float = 15, interval: float = 0.1
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_mira_healthy(host, port):
            return
        time.sleep(interval)
    raise RuntimeError("Mira's local service did not become ready in time.")


class LocalMiraServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.server = None
        self.thread: threading.Thread | None = None
        self.owned = False

    def start(self) -> None:
        if is_mira_healthy(self.host, self.port):
            return

        import uvicorn

        config = uvicorn.Config(
            "mira.main:app",
            host=self.host,
            port=self.port,
            log_level=os.getenv("MIRA_LOG_LEVEL", "warning"),
        )
        self.server = uvicorn.Server(config)
        self.server.install_signal_handlers = lambda: None
        self.thread = threading.Thread(
            target=self.server.run, name="mira-local-server", daemon=True
        )
        self.thread.start()
        self.owned = True
        try:
            wait_until_healthy(self.host, self.port)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self.owned or self.server is None:
            return
        self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.owned = False


def run_desktop() -> None:
    load_local_env(PROJECT_ROOT / ".env")
    os.chdir(PROJECT_ROOT)
    host = os.getenv("MIRA_DESKTOP_HOST", "127.0.0.1")
    port = int(os.getenv("MIRA_DESKTOP_PORT", "8000"))
    server = LocalMiraServer(host, port)
    try:
        server.start()
        open_app_window(dashboard_url(host, port))
    finally:
        server.stop()


def main() -> None:
    try:
        run_desktop()
    except Exception as error:
        message = f"Mira could not start:\n\n{error}"
        print(message)
        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(None, message, "Mira", 0x10)
            except Exception:
                pass
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

