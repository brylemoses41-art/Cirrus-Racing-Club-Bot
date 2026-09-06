from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event, Thread

import dashboard_v2


SESSION_FILE = Path(__file__).resolve().parent / "data" / "dashboard_sessions.json"
SAVE_INTERVAL = 2


def _load_sessions() -> None:
    try:
        if not SESSION_FILE.exists():
            return
        raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        now = time.time()
        for token, session in raw.items():
            if isinstance(session, dict) and float(session.get("expires", 0)) > now:
                dashboard_v2.SESSIONS[str(token)] = session
    except Exception as exc:
        print(f"Dashboard session restore skipped: {exc}")


def _save_sessions() -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    active = {
        token: session
        for token, session in dashboard_v2.SESSIONS.items()
        if isinstance(session, dict) and float(session.get("expires", 0)) > now
    }
    temp = SESSION_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(active, indent=2), encoding="utf-8")
    temp.replace(SESSION_FILE)


def install() -> None:
    _load_sessions()

    original_send_header = dashboard_v2.DashboardHandler.send_header

    def send_header(self, keyword, value):
        # Lax is more reliable when the dashboard is opened through a hosted
        # forwarded URL while remaining protected by HttpOnly server sessions.
        if keyword.lower() == "set-cookie" and value.startswith("crc_session="):
            value = value.replace("SameSite=Strict", "SameSite=Lax")
        return original_send_header(self, keyword, value)

    dashboard_v2.DashboardHandler.send_header = send_header

    stop = Event()

    def saver() -> None:
        while not stop.wait(SAVE_INTERVAL):
            try:
                _save_sessions()
            except Exception as exc:
                print(f"Dashboard session save skipped: {exc}")

    Thread(target=saver, name="crc-dashboard-session-store", daemon=True).start()

    original_start = dashboard_v2.start_dashboard

    def start_dashboard(port=dashboard_v2.DEFAULT_PORT):
        server = original_start(port)
        try:
            _save_sessions()
        except Exception:
            pass
        return server

    dashboard_v2.start_dashboard = start_dashboard
