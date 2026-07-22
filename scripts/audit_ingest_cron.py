#!/usr/bin/env python3
"""Ingest Hermes cron output files into the ops audit trail (automatic).

Agent jobs are prompted to call ops_audit.py, but models often forget.
This script scans cron/output/<job_id>/*.md for new runs and appends a
structured audit event from the ## Response section (or no_agent body).

Silent when nothing new. Safe to run every few minutes.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR, HERMES_HOME  # noqa: E402
from ops_audit import append_event, load_events  # noqa: E402

OUTPUT_ROOT = HERMES_HOME / "cron" / "output"
JOBS_FILE = HERMES_HOME / "cron" / "jobs.json"
STATE_FILE = BRAIN_DIR / "AUDIT_INGESTED.json"

# Agent (or hybrid) jobs — script-only jobs already call append_event themselves
INGEST_JOB_IDS = {
    "026c0a4c82b7",  # CI scan + autofix agent response
    "h11uilive23",  # UI live scan gate (may wake autofix)
    "c3pm0930",  # PM
    "d4exec1014",  # executor
    "e5market184",  # market
    "f6ops2100",  # daily ops review agent (digest script also audits)
}
EXECUTOR_JOB_IDS = {"d4exec1014", "d4execnight"}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _registry_status(job: dict) -> str:
    raw = str(job.get("last_status") or "").lower()
    if raw in {"ok", "silent", "partial", "blocked", "error"}:
        return raw
    if job.get("last_error") or raw in {"failed", "interrupted"}:
        return "error"
    return "partial"


def reconcile_executor_runs(
    jobs_by_id: dict,
    state: dict,
    events: list[dict],
    append_fn=append_event,
) -> int:
    """Guarantee an audit record when an executor produced no final response."""
    completed = state.setdefault("executor_last_runs", {})
    appended = 0
    for job_id in sorted(EXECUTOR_JOB_IDS):
        job = jobs_by_id.get(job_id) or {}
        run_raw = job.get("last_run_at")
        run_at = _parse_iso(run_raw)
        if not run_at or completed.get(job_id) == run_raw:
            continue
        previous_at = _parse_iso(completed.get(job_id))
        lower = previous_at or (run_at - timedelta(hours=2))
        upper = run_at + timedelta(minutes=5)
        covered = any(
            event.get("job_id") == job_id
            and (event_at := _parse_iso(event.get("ts"))) is not None
            and lower < event_at <= upper
            for event in events
        )
        if not covered:
            raw_status = str(job.get("last_status") or "unknown")
            detail = [
                f"scheduler last_status={raw_status}",
                f"last_run_at={run_raw}",
            ]
            if job.get("last_error"):
                detail.append(f"last_error={job['last_error']}")
            if job.get("last_delivery_error"):
                detail.append(f"last_delivery_error={job['last_delivery_error']}")
            append_fn(
                job_id=job_id,
                name=job.get("name") or job_id,
                status=_registry_status(job),
                summary="[registry-reconcile] Executor run had no direct/output audit event",
                detail="\n".join(detail),
                extra={
                    "source": "cron_registry_reconcile",
                    "last_run_at": run_raw,
                    "last_status": raw_status,
                },
            )
            appended += 1
        completed[job_id] = run_raw
    return appended


def load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"files": {}}
    return {"files": {}}


def save_state(state: dict) -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def job_names() -> dict[str, str]:
    if not JOBS_FILE.is_file():
        return {}
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {j.get("id"): j.get("name") or j.get("id") for j in data.get("jobs", [])}


def extract_response(text: str) -> str:
    # Prefer ## Response section (agent jobs)
    m = re.search(r"(?ms)^## Response\s*\n(.*)$", text)
    if m:
        return m.group(1).strip()
    # no_agent dumps: body after first ---
    if "**Mode:** no_agent" in text or "Mode:** no_agent" in text:
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    # Fallback: last 40 lines
    lines = text.strip().splitlines()
    return "\n".join(lines[-40:]).strip()


def infer_status(response: str, job_meta: dict | None) -> str:
    low = response.lower()
    if response.strip() == "[SILENT]" or low.strip() == "[silent]":
        return "silent"
    if re.search(
        r"(?im)^\s*(?:[-*]\s*)?(?:ACTION|APPROVAL)(?:\s+NEEDED)?\s*:",
        response,
    ):
        return "blocked"
    if "traceback" in low or "error:" in low[:500]:
        return "error"
    if "partial" in low or "halted" in low:
        return "partial"
    return "ok"


_PR_RE = re.compile(
    r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/\d+",
    re.I,
)
try:
    from ops_config import github_org
    _org = re.escape(github_org())
except Exception:
    _org = r"[\w.-]+"
_REPO_RE = re.compile(rf"\b({_org}/[\w.-]+)\b", re.I)
_GATE_RE = re.compile(r"\b((?:ACTION|APPROVAL):\s*[^\n]+)", re.I)


def extract_links(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    m = _PR_RE.search(text)
    if m:
        out["pr_url"] = m.group(0)
        out["repo"] = m.group(1)
    if "repo" not in out:
        m2 = _REPO_RE.search(text)
        if m2:
            out["repo"] = m2.group(1)
    g = _GATE_RE.search(text)
    if g:
        out["human_gate"] = g.group(1).strip()[:240]
    return out


def summarize(response: str, limit: int = 240) -> str:
    # First non-empty substantive line
    for ln in response.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("```"):
            continue
        if s.startswith("- ") or s.startswith("* "):
            s = s[2:].strip()
        if len(s) > limit:
            return s[: limit - 1] + "…"
        return s
    return "(no response summary)"


def detail_bullets(response: str, max_lines: int = 8) -> str:
    bullets = []
    for ln in response.splitlines():
        s = ln.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s[2:].strip())
        if len(bullets) >= max_lines:
            break
    if bullets:
        return "\n".join(bullets)
    # fallback: first few non-empty lines after summary
    lines = [ln.strip() for ln in response.splitlines() if ln.strip()][:max_lines]
    return "\n".join(lines[1:max_lines] if len(lines) > 1 else lines)


def parse_run_stamp(name: str) -> str | None:
    # 2026-07-17_10-12-49.md
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})\.md$", name)
    if not m:
        return None
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}"


def main() -> int:
    names = job_names()
    jobs_by_id = {}
    if JOBS_FILE.is_file():
        try:
            jobs_by_id = {
                j["id"]: j
                for j in json.loads(JOBS_FILE.read_text(encoding="utf-8")).get("jobs", [])
            }
        except json.JSONDecodeError:
            pass

    state = load_state()
    seen: dict = state.setdefault("files", {})
    ingested = 0

    if not OUTPUT_ROOT.is_dir():
        return 0

    for job_id in sorted(INGEST_JOB_IDS):
        folder = OUTPUT_ROOT / job_id
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            key = f"{job_id}/{path.name}"
            if key in seen:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Prompt-only/interrupted artifacts contain policy words such as
            # ACTION, blocked, and error; never infer an outcome from them.
            if "## Response" not in text:
                seen[key] = {
                    "skipped": "missing_response",
                    "at": datetime.now().isoformat(),
                }
                continue
            response = extract_response(text)
            if not response:
                seen[key] = {"skipped": "empty", "at": datetime.now().isoformat()}
                continue
            if response.strip() == "[SILENT]":
                status = "silent"
                summary = "Agent returned [SILENT]"
                detail = ""
            else:
                status = infer_status(response, jobs_by_id.get(job_id))
                summary = summarize(response)
                detail = detail_bullets(response)

            links = extract_links(response)
            arts = [str(path)]
            if links.get("pr_url"):
                arts.append(links["pr_url"])
            append_event(
                job_id=job_id,
                name=names.get(job_id, job_id),
                status=status,
                summary=f"[auto-ingest] {summary}",
                detail=detail,
                artifacts=arts,
                repo=links.get("repo", ""),
                pr_url=links.get("pr_url", ""),
                human_gate=links.get("human_gate", ""),
                extra={
                    "source": "cron_output_ingest",
                    "output_file": path.name,
                    "run_stamp": parse_run_stamp(path.name),
                },
            )
            seen[key] = {
                "ingested_at": datetime.now().isoformat(),
                "status": status,
                "summary": summary[:200],
            }
            ingested += 1

    ingested += reconcile_executor_runs(jobs_by_id, state, load_events())
    save_state(state)
    # Silent always — audit trail is the record; no Telegram for routine ingest
    return 0


if __name__ == "__main__":
    sys.exit(main())
