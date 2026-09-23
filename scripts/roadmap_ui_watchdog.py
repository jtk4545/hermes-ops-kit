#!/usr/bin/env python3
"""Ensure roadmap UI (server.py on :8888) is running.

Cron no_agent entrypoint must stay a .py file: a stale gateway process may still
treat .cmd/.sh as Python until fully restarted.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PORT = 8888
CHECK_HOST = "127.0.0.1"
SCRIPTS = Path(__file__).resolve().parent
SERVER = SCRIPTS / "server.py"


def port_open() -> bool:
    try:
        with socket.create_connection((CHECK_HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def lan_base_urls() -> list[str]:
    urls: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127."):
            urls.append(f"http://{ip}:{PORT}/")
    except OSError:
        pass
    return urls


def resolve_python() -> str:
    cands: list[str] = []
    env_py = (os.environ.get("HERMES_PYTHON") or "").strip()
    if env_py:
        cands.append(env_py)
    local = os.environ.get("LOCALAPPDATA") or ""
    appdata = os.environ.get("APPDATA") or ""
    try:
        pin = Path(local) / "hermes" / "HERMES_PYTHON.txt"
        if pin.is_file():
            cands.append(pin.read_text(encoding="utf-8").strip().splitlines()[0].strip())
    except Exception:
        pass
    for root in (
        Path(appdata) / "uv" / "python",
        Path(local).parent / "Roaming" / "uv" / "python" if local else Path(),
    ):
        if root.is_dir():
            for child in sorted(root.glob("cpython-*/python.exe"), reverse=True):
                cands.append(str(child))
    cands.append(sys.executable)
    seen: set[str] = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        p = Path(c)
        if not p.is_file():
            continue
        low = str(p).lower().replace("/", "\\")
        # Skip WDAC-blocked venv python when alternatives exist
        if "hermes-agent\\venv\\scripts\\python" in low and len(cands) > 1:
            continue
        return str(p)
    return sys.executable


def _audit(status: str, summary: str, artifacts: list[str] | None = None) -> None:
    try:
        sys.path.insert(0, str(SCRIPTS))
        from ops_audit import append_event  # type: ignore

        append_event(
            job_id="g7ui5m",
            name="Roadmap UI watchdog",
            status=status,
            summary=summary[:400],
            artifacts=artifacts or [],
        )
    except Exception:
        pass


def main() -> int:
    if port_open():
        return 0
    if not SERVER.is_file():
        print(f"Roadmap UI: missing {SERVER}")
        _audit("error", f"Missing server.py at {SERVER}")
        return 1

    py = resolve_python()
    log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "roadmap_ui.log"
    out = open(log_path, "a", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("HERMES_UI_HOST", "0.0.0.0")
    env["HERMES_PYTHON"] = py
    site = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "hermes"
        / "hermes-agent"
        / "venv"
        / "Lib"
        / "site-packages"
    )
    pp = str(SCRIPTS)
    if site.is_dir():
        pp = pp + os.pathsep + str(site)
    env["PYTHONPATH"] = pp + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )  # type: ignore[attr-defined]

    try:
        subprocess.Popen(
            [py, str(SERVER)],
            cwd=str(SCRIPTS),
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
            env=env,
        )
    except OSError as exc:
        msg = f"Roadmap UI start blocked: {exc} (python={py})"
        try:
            out.write(msg + "\n")
            out.flush()
        except Exception:
            pass
        print(msg)
        _audit("error", msg, [str(log_path)])
        return 0

    for _ in range(25):
        time.sleep(0.2)
        if port_open():
            arts = [f"http://127.0.0.1:{PORT}/"] + lan_base_urls()
            _audit("ok", f"Started roadmap UI on :8888 via {Path(py).name}", arts)
            return 0

    print(f"Roadmap UI start attempted; port {PORT} not open yet — see {log_path}")
    _audit("partial", "Start attempted; port not open yet", [str(log_path)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
