#!/usr/bin/env python3
"""Load Hermes cron jobs and expand future run times (for ops UI)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from ops_config import timezone_name as _tz_name
except Exception:
    def _tz_name():
        return 'America/Chicago'

from croniter import croniter

TZ = ZoneInfo(_tz_name())
try:
    from hermes_paths import hermes_home
except Exception:
    def hermes_home():
        env = os.environ.get("HERMES_HOME", "").strip()
        if env:
            return Path(env)
        return Path.home() / ".local" / "share" / "hermes"

HERMES_HOME = hermes_home()
JOBS_FILE = HERMES_HOME / "cron" / "jobs.json"
RUNNING_JOBS_FILE = HERMES_HOME / "cron" / "running_jobs.json"
STATE_DB = HERMES_HOME / "state.db"
ACTIVE_SESSION_LOOKBACK_SECONDS = 3 * 60 * 60
ACTIVE_SESSION_ACTIVITY_SECONDS = 15 * 60

# Timeline noise by default (still shown in registry). Includes */5…*/30.
FREQUENT_THRESH_MINUTES = 30

# Short “what this job does” for the registry UI (keyed by job id).
JOB_DESCRIPTIONS: dict[str, str] = {
    "a1brain0600": "Consolidate shared brain files and refresh INDEX so chat + cron share one SoT.",
    "41cb7755ae6d": "Local health check across repos (lint/tests/tools); writes findings into PIPELINES.",
    "026c0a4c82b7": "Scan CI on main/dev/qa; on failures wake autofix to open ≤1 hermes-autofix PR per repo.",
    "b2prmon30m": "Watch hermes-exec / hermes-autofix PRs; merge-on-green or Telegram APPROVAL / RED alerts.",
    "c3pm0930": "Product manager: classify roadmap agent vs human, set HITL gates, brief top agent work.",
    "d4exec1014": "20–30m executor window: decompose big items onto the roadmap, ship prioritized slices, add follow-ups; hermes-exec PRs / HITL.",
    "e5market184": "US market + buyer scan for products; write MARKET/BUYERS brain sections; silent if unchanged.",
    "f6ops2100": "End-of-day digest + review: grade jobs from AUDIT, safe improvements, always Telegram day report.",
    "g7ui5m": "Keep the ops UI (roadmap/jobs/audit) running on :8888; restart server.py if the port is down.",
    "g8sync0615": "Sync scripts, skills, and design docs between HERMES_HOME and ~/.hermes mirrors.",
    "g9auditingest": "Backfill agent cron outputs into AUDIT.jsonl when the model forgot to call ops_audit.",
    "g10humanq": "Needs-you queue: Telegram reminders with exponential backoff; detect UI “release to agent”.",
    "h12gcloud0730": "Optional GCP read-only ops/cost scan → PIPELINES/COSTS (no autofix wake).",
    "h11uilive23": "Optional UI/e2e GHA scan; local live checks only when HERMES_UI_LIVE_RUN=1.",
}


def _now() -> datetime:
    return datetime.now(TZ)


def cron_expr(job: dict) -> str:
    sched = job.get("schedule") or {}
    if isinstance(sched, dict) and sched.get("expr"):
        return str(sched["expr"])
    return str(job.get("schedule_display") or "").strip()


def summarize_cron(expr: str) -> str:
    """Short human label for common patterns."""
    e = (expr or "").strip()
    hints = {
        "0 6 * * *": "Daily 06:00",
        "15 6 * * *": "Daily 06:15",
        "0 7 * * *": "Daily 07:00",
        "0 8,12,16,20 * * 1-5": "Weekdays 08/12/16/20",
        "0 8,12,16,20 * * *": "Daily 08/12/16/20",
        "*/30 * * * *": "Every 30 min",
        "30 9 * * 1-5": "Weekdays 09:30",
        "30 9 * * *": "Daily 09:30",
        "0 10,14 * * 1-5": "Weekdays 10:00 & 14:00",
        "0 10,14 * * *": "Daily 10:00 & 14:00",
        "0 18 * * 1,4": "Mon & Thu 18:00",
        "0 18 * * *": "Daily 18:00",
        "0 21 * * *": "Daily 21:00",
        "*/5 * * * *": "Every 5 min",
        "*/10 * * * *": "Every 10 min",
        "*/15 * * * *": "Every 15 min",
    }
    return hints.get(e, e or "(no schedule)")


def is_frequent(expr: str) -> bool:
    e = (expr or "").strip()
    if e.startswith("*/"):
        try:
            n = int(e.split()[0][2:])
            return n <= FREQUENT_THRESH_MINUTES
        except ValueError:
            return False
    return False


def load_jobs_raw() -> list[dict]:
    if not JOBS_FILE.is_file():
        return []
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(data.get("jobs") or [])


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _snapshot_running_job_ids() -> set[str]:
    try:
        payload = json.loads(RUNNING_JOBS_FILE.read_text(encoding="utf-8"))
        pid = int(payload.get("pid") or 0)
        ids = payload.get("job_ids") or []
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return set()
    if not _pid_alive(pid):
        return set()
    return {str(job_id) for job_id in ids if job_id}


def _active_session_job_ids() -> set[str]:
    """Compatibility fallback for gateways without running_jobs.json."""
    if not STATE_DB.is_file():
        return set()
    now = time.time()
    ids: set[str] = set()
    try:
        con = sqlite3.connect(
            f"file:{STATE_DB.as_posix()}?mode=ro",
            uri=True,
            timeout=1,
        )
        try:
            rows = con.execute(
                """
                select s.id
                from sessions s
                where s.source='cron'
                  and s.ended_at is null
                  and s.started_at >= ?
                  and coalesce(
                        (select max(m.timestamp) from messages m where m.session_id=s.id),
                        s.started_at
                      ) >= ?
                """,
                (
                    now - ACTIVE_SESSION_LOOKBACK_SECONDS,
                    now - ACTIVE_SESSION_ACTIVITY_SECONDS,
                ),
            )
            for (session_id,) in rows:
                match = re.fullmatch(
                    r"cron_(.+)_\d{8}_\d{6}",
                    str(session_id or ""),
                )
                if match:
                    ids.add(match.group(1))
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return set()
    return ids


def _running_script_job_ids(raw_jobs: list[dict]) -> set[str]:
    scripts = {
        str(job.get("id")): Path(str(job.get("script"))).name.lower()
        for job in raw_jobs
        if job.get("script")
    }
    if not scripts:
        return set()
    try:
        import psutil
    except ImportError:
        return set()
    running: set[str] = set()
    try:
        for process in psutil.process_iter(["cmdline"]):
            command = " ".join(process.info.get("cmdline") or []).lower()
            for job_id, script_name in scripts.items():
                if script_name and script_name in command:
                    running.add(job_id)
    except (OSError, RuntimeError):
        pass
    return running


def running_job_ids() -> set[str]:
    raw_jobs = load_jobs_raw()
    return (
        _snapshot_running_job_ids()
        | _active_session_job_ids()
        | _running_script_job_ids(raw_jobs)
    )


def _is_due_now(job: dict, *, now: datetime | None = None) -> bool:
    if not job.get("enabled", True) or not job.get("next_run_at"):
        return False
    try:
        due = datetime.fromisoformat(str(job["next_run_at"]).replace("Z", "+00:00"))
        current = now or _now()
        if due.tzinfo is None:
            due = due.replace(tzinfo=TZ)
        return due <= current.astimezone(TZ)
    except (TypeError, ValueError):
        return False


def job_description(job: dict) -> str:
    jid = str(job.get("id") or "")
    if jid in JOB_DESCRIPTIONS:
        return JOB_DESCRIPTIONS[jid]
    # Fallback from job fields if a new cron appears before the map is updated
    if job.get("no_agent") and job.get("script"):
        return f"Runs script {job.get('script')} on schedule."
    if job.get("script"):
        return f"Hybrid: runs {job.get('script')} then may wake an agent."
    return "Agent cron — see OPS_DESIGN.md for expectation."


def job_public(job: dict) -> dict:
    expr = cron_expr(job)
    prompt = job.get("prompt") or ""
    return {
        "id": job.get("id"),
        "name": job.get("name") or job.get("id"),
        "description": job_description(job),
        "enabled": bool(job.get("enabled", True)),
        "state": job.get("state"),
        "no_agent": bool(job.get("no_agent")),
        "script": job.get("script"),
        "skills": job.get("skills") or ([] if not job.get("skill") else [job.get("skill")]),
        "provider": job.get("provider") or job.get("provider_snapshot"),
        "model": job.get("model") or job.get("model_snapshot"),
        "deliver": job.get("deliver"),
        "schedule_expr": expr,
        "schedule_label": summarize_cron(expr),
        "frequent": is_frequent(expr),
        "next_run_at": job.get("next_run_at"),
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_error": (job.get("last_error") or "")[:240] or None,
        "last_delivery_error": job.get("last_delivery_error"),
        "mode": "script" if job.get("no_agent") else ("hybrid" if job.get("script") else "agent"),
        "prompt_chars": len(prompt),
        "has_prompt": bool(prompt.strip()),
    }


def expand_fires(
    expr: str,
    *,
    start: datetime | None = None,
    horizon_hours: int = 72,
    max_fires: int = 80,
) -> list[str]:
    if not expr:
        return []
    start = start or _now()
    end = start + timedelta(hours=max(1, horizon_hours))
    try:
        it = croniter(expr, start)
    except (ValueError, KeyError, TypeError):
        return []
    out: list[str] = []
    for _ in range(max(1, max_fires)):
        nxt = it.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=TZ)
        else:
            nxt = nxt.astimezone(TZ)
        if nxt > end:
            break
        out.append(nxt.isoformat())
    return out


def jobs_payload() -> dict:
    raw_jobs = load_jobs_raw()
    running = running_job_ids()
    now = _now()
    jobs = []
    for raw in raw_jobs:
        public = job_public(raw)
        public["running"] = str(public.get("id")) in running
        public["queued"] = not public["running"] and _is_due_now(raw, now=now)
        public["can_run"] = bool(
            public["enabled"] and not public["running"] and not public["queued"]
        )
        jobs.append(public)
    jobs.sort(key=lambda j: (not j["enabled"], j.get("schedule_expr") or "", j["name"] or ""))
    return {
        "generated_at": _now().isoformat(),
        "jobs_file": str(JOBS_FILE),
        "count": len(jobs),
        "jobs": jobs,
    }


# Visual system map: columns = purpose stages; buses = shared state.
GRAPH_LANES = [
    {"id": "foundations", "title": "Foundations", "subtitle": "Keep the SoT & UI alive"},
    {"id": "sense", "title": "Sense", "subtitle": "What is broken / unhealthy"},
    {"id": "plan", "title": "Plan", "subtitle": "What should we do next"},
    {"id": "build", "title": "Build", "subtitle": "Change code safely"},
    {"id": "ship", "title": "Ship", "subtitle": "Land PRs when green"},
    {"id": "govern", "title": "Govern", "subtitle": "Humans + day review"},
]

# Fixed layout in viewBox units (0–1200 × 0–780)
GRAPH_LAYOUT: dict[str, dict] = {
    # buses (shared state)
    "bus_brain": {"x": 100, "y": 70, "lane": "foundations", "kind": "bus"},
    "bus_roadmap": {"x": 520, "y": 70, "lane": "plan", "kind": "bus"},
    "bus_github": {"x": 900, "y": 70, "lane": "ship", "kind": "bus"},
    "bus_audit": {"x": 100, "y": 700, "lane": "govern", "kind": "bus"},
    "bus_telegram": {"x": 900, "y": 700, "lane": "govern", "kind": "bus"},
    # jobs
    "a1brain0600": {"x": 100, "y": 200, "lane": "foundations", "kind": "job"},
    "g8sync0615": {"x": 100, "y": 310, "lane": "foundations", "kind": "job"},
    "g7ui5m": {"x": 100, "y": 420, "lane": "foundations", "kind": "job"},
    "g9auditingest": {"x": 100, "y": 530, "lane": "foundations", "kind": "job"},
    "41cb7755ae6d": {"x": 300, "y": 240, "lane": "sense", "kind": "job"},
    "026c0a4c82b7": {"x": 300, "y": 400, "lane": "sense", "kind": "job"},
    "e5market184": {"x": 520, "y": 220, "lane": "plan", "kind": "job"},
    "c3pm0930": {"x": 520, "y": 380, "lane": "plan", "kind": "job"},
    "d4exec1014": {"x": 720, "y": 320, "lane": "build", "kind": "job"},
    "b2prmon30m": {"x": 900, "y": 320, "lane": "ship", "kind": "job"},
    "g10humanq": {"x": 720, "y": 520, "lane": "govern", "kind": "job"},
    "f6ops2100": {"x": 520, "y": 600, "lane": "govern", "kind": "job"},
}

BUS_META = {
    "bus_brain": {
        "label": "Shared brain",
        "why": "Filesystem bus (PRODUCTS, PIPELINES, MARKET, PRINCIPLES…). Chat + cron both read/write here.",
    },
    "bus_roadmap": {
        "label": "Roadmap",
        "why": "Agent vs human ownership, blocked gates, Needs you panel — what work is allowed next.",
    },
    "bus_github": {
        "label": "GitHub PRs",
        "why": "hermes-exec / hermes-autofix PRs + checks. Merge-on-green lives here.",
    },
    "bus_audit": {
        "label": "AUDIT trail",
        "why": "What each job did / blocked. Digest + daily review grade from this SoT.",
    },
    "bus_telegram": {
        "label": "Telegram",
        "why": "Failures, HITL, merge holds, human-queue backoff, always-on daily ops report.",
    },
}

# why = reason the edge exists (shown on the map)
GRAPH_EDGES = [
    {"from": "a1brain0600", "to": "bus_brain", "label": "refresh INDEX / consolidate"},
    {"from": "g8sync0615", "to": "a1brain0600", "label": "mirrors stay in sync for scripts"},
    {"from": "g7ui5m", "to": "bus_roadmap", "label": "UI on :8888 for roadmap / jobs / audit"},
    {"from": "bus_brain", "to": "41cb7755ae6d", "label": "context for health notes"},
    {"from": "41cb7755ae6d", "to": "bus_brain", "label": "write PIPELINES health"},
    {"from": "bus_brain", "to": "026c0a4c82b7", "label": "PRODUCTS / PIPELINES before fix"},
    {"from": "026c0a4c82b7", "to": "bus_github", "label": "open hermes-autofix PRs on red CI"},
    {"from": "026c0a4c82b7", "to": "bus_brain", "label": "update PIPELINES after scan"},
    {"from": "bus_brain", "to": "e5market184", "label": "read PRODUCTS / MARKET / BUYERS"},
    {"from": "e5market184", "to": "bus_brain", "label": "write latest market + buyers"},
    {"from": "bus_brain", "to": "c3pm0930", "label": "brain-first PM brief"},
    {"from": "e5market184", "to": "c3pm0930", "label": "market signals inform roadmap"},
    {"from": "c3pm0930", "to": "bus_roadmap", "label": "owner=agent|human + HITL fields"},
    {
        "from": "bus_roadmap",
        "to": "d4exec1014",
        "label": "pick unblocked agent item (or resume after Release)",
    },
    {"from": "bus_brain", "to": "d4exec1014", "label": "PRODUCTS / PRINCIPLES / PR_QUALITY"},
    {"from": "d4exec1014", "to": "bus_github", "label": "open hermes-exec PR + auto-merge"},
    {"from": "d4exec1014", "to": "bus_roadmap", "label": "Done / or block with human_actions"},
    {"from": "bus_github", "to": "b2prmon30m", "label": "poll labeled PRs every 30m"},
    {"from": "b2prmon30m", "to": "bus_github", "label": "merge green; hold if APPROVAL"},
    {"from": "b2prmon30m", "to": "bus_telegram", "label": "GREEN / RED / APPROVAL alerts"},
    {"from": "bus_roadmap", "to": "g10humanq", "label": "Needs you queue"},
    {"from": "g10humanq", "to": "bus_telegram", "label": "exponential backoff reminders"},
    {"from": "g10humanq", "to": "bus_roadmap", "label": "detect Release → agent"},
    {"from": "026c0a4c82b7", "to": "g9auditingest", "label": "cron output if audit forgotten"},
    {"from": "c3pm0930", "to": "g9auditingest", "label": "cron output → AUDIT"},
    {"from": "d4exec1014", "to": "g9auditingest", "label": "cron output → AUDIT"},
    {"from": "g9auditingest", "to": "bus_audit", "label": "append structured events"},
    {"from": "b2prmon30m", "to": "bus_audit", "label": "audit merges / holds"},
    {"from": "g10humanq", "to": "bus_audit", "label": "audit reminders / resolves"},
    {"from": "bus_audit", "to": "f6ops2100", "label": "day scorecard SoT"},
    {"from": "f6ops2100", "to": "bus_telegram", "label": "always send OPS DAY REPORT"},
    {"from": "f6ops2100", "to": "bus_brain", "label": "changelog + daily reports"},
    {"from": "c3pm0930", "to": "bus_telegram", "label": "HITL packet when queue nonempty"},
    {"from": "d4exec1014", "to": "bus_telegram", "label": "HITL when blocked / idle human queue"},
]


def graph_payload() -> dict:
    by_id = {j["id"]: j for j in (job_public(r) for r in load_jobs_raw())}
    nodes = []
    for nid, lay in GRAPH_LAYOUT.items():
        if lay["kind"] == "bus":
            meta = BUS_META.get(nid, {})
            nodes.append(
                {
                    "id": nid,
                    "kind": "bus",
                    "lane": lay["lane"],
                    "x": lay["x"],
                    "y": lay["y"],
                    "label": meta.get("label", nid),
                    "why": meta.get("why", ""),
                    "description": meta.get("why", ""),
                    "mode": "bus",
                    "schedule_label": "always on (state)",
                    "enabled": True,
                }
            )
        else:
            job = by_id.get(nid, {})
            nodes.append(
                {
                    "id": nid,
                    "kind": "job",
                    "lane": lay["lane"],
                    "x": lay["x"],
                    "y": lay["y"],
                    "label": job.get("name") or nid,
                    "why": JOB_DESCRIPTIONS.get(nid, job.get("description") or ""),
                    "description": job.get("description") or JOB_DESCRIPTIONS.get(nid, ""),
                    "mode": job.get("mode") or "script",
                    "schedule_label": job.get("schedule_label") or "",
                    "model": job.get("model"),
                    "script": job.get("script"),
                    "enabled": job.get("enabled", True),
                    "last_status": job.get("last_status"),
                    "next_run_at": job.get("next_run_at"),
                }
            )
    story = [
        "Foundations keep brain, mirrors, UI, and AUDIT trustworthy.",
        "Sense finds local/CI pain → autofix opens PRs.",
        "Plan turns brain + market into roadmap ownership and HITL.",
        "Build (executor) implements one agent item; Ship merges green PRs.",
        "Govern nags humans until release, then day review grades the AUDIT trail.",
    ]
    return {
        "generated_at": _now().isoformat(),
        "viewBox": {"w": 1100, "h": 780},
        "lanes": GRAPH_LANES,
        "nodes": nodes,
        "edges": GRAPH_EDGES,
        "story": story,
    }


def timeline_payload(
    *,
    hours: int = 72,
    include_frequent: bool = False,
    max_per_job: int = 120,
) -> dict:
    hours = max(1, min(hours, 168 * 2))  # up to 14 days
    start = _now()
    events: list[dict] = []
    jobs_meta = []
    for raw in load_jobs_raw():
        pub = job_public(raw)
        jobs_meta.append(pub)
        if not pub["enabled"]:
            continue
        if pub["frequent"] and not include_frequent:
            continue
        expr = pub["schedule_expr"]
        for ts in expand_fires(expr, start=start, horizon_hours=hours, max_fires=max_per_job):
            events.append(
                {
                    "ts": ts,
                    "job_id": pub["id"],
                    "name": pub["name"],
                    "mode": pub["mode"],
                    "model": pub["model"],
                    "script": pub["script"],
                    "schedule_label": pub["schedule_label"],
                    "frequent": pub["frequent"],
                }
            )
    events.sort(key=lambda e: e["ts"])
    # Group by local day
    by_day: dict[str, list[dict]] = {}
    for e in events:
        day = e["ts"][:10]
        by_day.setdefault(day, []).append(e)
    return {
        "generated_at": start.isoformat(),
        "horizon_hours": hours,
        "include_frequent": include_frequent,
        "event_count": len(events),
        "days": [{"day": d, "events": by_day[d]} for d in sorted(by_day)],
        "jobs": jobs_meta,
        "hidden_frequent": [
            j["id"] for j in jobs_meta if j.get("frequent") and not include_frequent
        ],
    }


if __name__ == "__main__":
    print(json.dumps(timeline_payload(hours=48), indent=2)[:2000])
