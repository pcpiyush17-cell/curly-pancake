from __future__ import annotations

import json
import os
import threading
import time
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

    webview.create_window(
        "Mira — Execution Companion",
        url,
        width=1440,
        height=900,
        min_size=(960, 680),
        background_color="#0d1111",
    )
    webview.start(debug=os.getenv("MIRA_DESKTOP_DEBUG") == "1")


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
