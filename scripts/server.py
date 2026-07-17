#!/usr/bin/env python3
"""Ops dashboard server — roadmap UI + jobs timeline + audit trail on :8888."""

from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

ROADMAP_FILE = Path(os.path.expanduser("~/.hermes/roadmaps.json"))
HERMES_HOME = Path(
    os.environ.get("HERMES_HOME", Path(os.environ.get("LOCALAPPDATA", "")) / "hermes")
)
BRAIN_DIR = HERMES_HOME / "brain"
AUDIT_JSONL = BRAIN_DIR / "AUDIT.jsonl"
PHASES = ["In Progress", "Upcoming", "Backlog", "Done"]
try:
    from ops_config import product_names, load_config

    DEFAULT_PROJECTS = product_names()
    PORT = int(load_config().get("ui_port") or 8888)
except Exception:
    DEFAULT_PROJECTS = ["example-app"]
    PORT = 8888


def ensure_roadmap() -> dict:
    data: dict = {}
    if ROADMAP_FILE.exists():
        with open(ROADMAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
    changed = False
    for name in DEFAULT_PROJECTS:
        if name not in data:
            data[name] = {p: [] for p in PHASES}
            changed = True
        else:
            for phase in PHASES:
                if phase not in data[name]:
                    data[name][phase] = []
                    changed = True
    if changed or not ROADMAP_FILE.exists():
        ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return data


def load_audit_events(limit: int = 500) -> list[dict]:
    if not AUDIT_JSONL.is_file():
        return []
    events: list[dict] = []
    try:
        lines = AUDIT_JSONL.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for ln in lines[-max(1, limit) :]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return events


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPTS_DIR), **kwargs)

    def _send_json(self, payload: dict | list, code: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/roadmap.json", "/roadmaps.json"):
            self._send_json(ensure_roadmap())
            return
        if path in ("/api/audit", "/audit.json"):
            qs = parse_qs(parsed.query or "")
            try:
                limit = int((qs.get("limit") or ["500"])[0])
            except ValueError:
                limit = 500
            limit = max(1, min(limit, 5000))
            events = load_audit_events(limit)
            self._send_json(
                {
                    "count": len(events),
                    "path": str(AUDIT_JSONL),
                    "events": events,
                }
            )
            return
        if path in ("/api/jobs", "/jobs.json"):
            import importlib

            import jobs_schedule

            importlib.reload(jobs_schedule)
            self._send_json(jobs_schedule.jobs_payload())
            return
        if path in ("/api/jobs/timeline", "/jobs/timeline.json"):
            qs = parse_qs(parsed.query or "")
            try:
                hours = int((qs.get("hours") or ["72"])[0])
            except ValueError:
                hours = 72
            freq_raw = (qs.get("frequent") or ["0"])[0].lower()
            include_frequent = freq_raw in ("1", "true", "yes", "all")
            import importlib

            import jobs_schedule

            importlib.reload(jobs_schedule)
            self._send_json(
                jobs_schedule.timeline_payload(
                    hours=hours, include_frequent=include_frequent
                )
            )
            return
        if path in ("/api/jobs/graph", "/jobs/graph.json"):
            import importlib

            import jobs_schedule

            importlib.reload(jobs_schedule)
            self._send_json(jobs_schedule.graph_payload())
            return
        if path in ("/", "/index.html"):
            self.path = "/roadmap.html"
        elif path in ("/jobs", "/jobs.html"):
            self.path = "/jobs.html"
        elif path in ("/audit", "/audit.html"):
            self.path = "/audit.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/roadmap.json", "/roadmaps.json"):
            self.send_response(405)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        twin = SCRIPTS_DIR / "roadmap.json"
        with open(twin, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    ensure_roadmap()
    print(f"Roadmap SoT: {ROADMAP_FILE}")
    print(f"Audit JSONL: {AUDIT_JSONL}")
    print(f"Jobs file:   {HERMES_HOME / 'cron' / 'jobs.json'}")
    print(f"Roadmap UI:  http://127.0.0.1:{PORT}/")
    print(f"Jobs UI:     http://127.0.0.1:{PORT}/jobs")
    print(f"Audit UI:    http://127.0.0.1:{PORT}/audit")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
