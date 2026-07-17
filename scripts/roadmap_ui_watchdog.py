#!/usr/bin/env python3
"""Ensure roadmap UI (server.py on 8888) is running; start it if down."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

PORT = 8888
HOST = "127.0.0.1"
SCRIPTS = Path(__file__).resolve().parent
SERVER = SCRIPTS / "server.py"


def port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def main() -> int:
    if port_open():
        return 0  # silent — no audit spam every 5m
    if not SERVER.is_file():
        print(f"Roadmap UI: missing {SERVER}")
        try:
            from ops_audit import append_event

            append_event(
                job_id="g7ui5m",
                name="Roadmap UI watchdog",
                status="error",
                summary=f"Missing server.py at {SERVER}",
            )
        except Exception:
            pass
        return 1

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

    log = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "logs"
    log.mkdir(parents=True, exist_ok=True)
    out = open(log / "roadmap_ui.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, str(SERVER)],
        cwd=str(SCRIPTS),
        stdout=out,
        stderr=out,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    # brief wait
    import time

    for _ in range(20):
        time.sleep(0.25)
        if port_open():
            # Audit only — no Telegram for routine restart
            try:
                from ops_audit import append_event

                append_event(
                    job_id="g7ui5m",
                    name="Roadmap UI watchdog",
                    status="ok",
                    summary="Started roadmap UI on :8888",
                    artifacts=[f"http://{HOST}:{PORT}/"],
                )
            except Exception:
                pass
            return 0
    # Failure / needs attention — stdout becomes Telegram when deliver=telegram
    print(f"Roadmap UI start attempted but port {PORT} not open yet — check {log / 'roadmap_ui.log'}")
    try:
        from ops_audit import append_event

        append_event(
            job_id="g7ui5m",
            name="Roadmap UI watchdog",
            status="partial",
            summary="Start attempted; port not open yet",
            artifacts=[str(log / "roadmap_ui.log")],
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
