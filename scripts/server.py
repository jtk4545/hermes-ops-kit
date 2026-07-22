#!/usr/bin/env python3
"""Ops dashboard server — roadmap UI + jobs timeline + audit trail on :8888."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from hermes_paths import brain_dir, hermes_home, roadmap_file  # noqa: E402
from roadmap_history import normalize_roadmap, reconcile_update  # noqa: E402

ROADMAP_FILE = roadmap_file()
HERMES_HOME = hermes_home()
BRAIN_DIR = brain_dir()
AUDIT_JSONL = BRAIN_DIR / "AUDIT.jsonl"
_env_registry = os.environ.get("HERMES_INSTANCE_REGISTRY", "").strip()
INSTANCE_REGISTRY_FILE = (
    Path(_env_registry).expanduser() if _env_registry else SCRIPTS_DIR / "instances.json"
)
PHASES = ["In Progress", "Upcoming", "Backlog", "Done"]
# Default localhost-only for kit safety. LAN: HERMES_UI_HOST=0.0.0.0 (no auth — trusted network only).
BIND_HOST = os.environ.get("HERMES_UI_HOST", "127.0.0.1")
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_job_run_request_lock = threading.Lock()
try:
    from ops_config import product_names, load_config

    DEFAULT_PROJECTS = product_names()
    PORT = int(load_config().get("ui_port") or 8888)
except Exception:
    DEFAULT_PROJECTS = ["example-app"]
    PORT = 8888


class JobRunConflict(RuntimeError):
    pass


class JobRunNotFound(LookupError):
    pass


def _job_status(job_id: str) -> dict:
    import importlib

    import jobs_schedule

    importlib.reload(jobs_schedule)
    for job in jobs_schedule.jobs_payload()["jobs"]:
        if str(job.get("id")) == job_id:
            return {
                "exists": True,
                "enabled": bool(job.get("enabled")),
                "running": bool(job.get("running")),
                "queued": bool(job.get("queued")),
            }
    return {"exists": False, "enabled": False, "running": False, "queued": False}


def _queue_job_for_next_tick(job_id: str) -> dict | None:
    """Queue through Hermes; never execute an agent inside the HTTP request."""
    try:
        from cron.jobs import trigger_job
    except ImportError as exc:
        raise RuntimeError(
            "cron.jobs.trigger_job unavailable — run inside a Hermes install "
            "with the cron package on PYTHONPATH"
        ) from exc
    return trigger_job(job_id)


def trigger_job_once(job_id: str) -> dict:
    if not JOB_ID_RE.fullmatch(job_id or ""):
        raise JobRunNotFound("Job not found")
    with _job_run_request_lock:
        status = _job_status(job_id)
        if not status["exists"]:
            raise JobRunNotFound("Job not found")
        if not status["enabled"]:
            raise JobRunConflict("Job is disabled")
        if status["running"]:
            raise JobRunConflict("Job is already running")
        if status["queued"]:
            raise JobRunConflict("Job is already queued")
        if not _queue_job_for_next_tick(job_id):
            raise JobRunNotFound("Job not found")
        return {
            "ok": True,
            "job_id": job_id,
            "state": "queued",
            "message": "Queued for the next scheduler tick",
        }


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
    if normalize_roadmap(data):
        changed = True
    if changed or not ROADMAP_FILE.exists():
        ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return data


def validate_roadmap_done_transitions(previous: dict, incoming: dict) -> None:
    """Require an explicit instance-impact acknowledgment for newly Done items."""
    if not isinstance(incoming, dict):
        raise ValueError("Roadmap payload must be an object")
    previously_done = {
        (project, item.get("name"))
        for project, phases in previous.items()
        if isinstance(phases, dict)
        for item in phases.get("Done", [])
        if isinstance(item, dict)
    }
    allowed = {"no impact", "added", "changed", "removed"}
    for project, phases in incoming.items():
        if not isinstance(phases, dict):
            raise ValueError(f"Invalid phases for project {project}")
        for item in phases.get("Done", []):
            if not isinstance(item, dict):
                raise ValueError(f"Invalid Done item for project {project}")
            identity = (project, item.get("name"))
            if identity in previously_done:
                continue
            impact = str(item.get("instance_impact", "")).strip().lower()
            if impact not in allowed:
                raise ValueError(
                    f"Instance impact is required before Done: {project} / {item.get('name', 'unnamed')}"
                )
            if impact != "no impact" and not str(item.get("instance_evidence", "")).strip():
                raise ValueError(
                    f"Instance evidence is required for impact '{impact}': "
                    f"{project} / {item.get('name', 'unnamed')}"
                )


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


def load_instances_payload() -> dict:
    from instances_registry import load_instance_registry

    return load_instance_registry(INSTANCE_REGISTRY_FILE)


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
        if path in ("/api/instances", "/instances.json"):
            self._send_json(load_instances_payload())
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
        if path in ("/api/checkin", "/checkin.json"):
            import importlib

            import checkin

            importlib.reload(checkin)
            qs = parse_qs(parsed.query or "")
            refresh = (qs.get("refresh") or ["0"])[0].lower() in ("1", "true", "yes")
            self._send_json(checkin.checkin_payload(refresh_prs=refresh))
            return
        if path in ("/api/open-prs", "/open-prs.json"):
            import importlib

            import checkin

            importlib.reload(checkin)
            qs = parse_qs(parsed.query or "")
            refresh = (qs.get("refresh") or ["0"])[0].lower() in ("1", "true", "yes")
            self._send_json(checkin.load_open_prs(force_refresh=refresh))
            return
        if path in ("/", "/index.html"):
            self.path = "/roadmap.html"
        elif path in ("/instances", "/instances.html"):
            self.path = "/instances.html"
        elif path in ("/jobs", "/jobs.html"):
            self.path = "/jobs.html"
        elif path in ("/audit", "/audit.html"):
            self.path = "/audit.html"
        elif path in ("/checkin", "/checkin.html"):
            self.path = "/checkin.html"
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/instances/verify":
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 65536:
                self._send_json({"ok": False, "error": "invalid request size"}, 400)
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("JSON body must be an object")
                from instances_registry import record_instance_verification

                payload = record_instance_verification(
                    INSTANCE_REGISTRY_FILE,
                    product=body.get("product", ""),
                    environment=body.get("environment", ""),
                    method=body.get("method", ""),
                    evidence_url=body.get("evidence_url", ""),
                    note=body.get("note", ""),
                    actor="human",
                )
                self._send_json({"ok": True, **payload})
            except KeyError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 404)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 400)
            except OSError as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        match = re.fullmatch(r"/api/jobs/([^/]+)/run", path)
        if match:
            job_id = unquote(match.group(1))
            try:
                self._send_json(trigger_job_once(job_id), 202)
            except JobRunNotFound as exc:
                self._send_json({"ok": False, "error": str(exc)}, 404)
            except JobRunConflict as exc:
                self._send_json({"ok": False, "error": str(exc)}, 409)
            except (ImportError, RuntimeError, OSError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, 503)
            return
        if path not in ("/roadmap.json", "/roadmaps.json"):
            self.send_response(405)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Roadmap payload must be an object")
            previous = ensure_roadmap()
            validate_roadmap_done_transitions(previous, data)
            reconcile_update(previous, data, actor="human-ui")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return
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
    print(f"Instances:   {INSTANCE_REGISTRY_FILE}")
    print(f"Jobs file:   {HERMES_HOME / 'cron' / 'jobs.json'}")
    print(f"Bind:        {BIND_HOST}:{PORT}")
    print(f"Roadmap UI:  http://127.0.0.1:{PORT}/")
    print(f"Check-in:    http://127.0.0.1:{PORT}/checkin")
    print(f"Instances:   http://127.0.0.1:{PORT}/instances")
    print(f"Jobs UI:     http://127.0.0.1:{PORT}/jobs")
    print(f"Audit UI:    http://127.0.0.1:{PORT}/audit")
    if BIND_HOST in ("0.0.0.0", "::"):
        print(
            "Note: bound on all interfaces (no auth). "
            "Use only on a trusted LAN. Default kit bind is 127.0.0.1."
        )
    else:
        print(
            "Note: localhost-only bind. For LAN access set HERMES_UI_HOST=0.0.0.0 "
            "(no auth — trusted network only)."
        )
    ThreadingHTTPServer((BIND_HOST, PORT), Handler).serve_forever()
