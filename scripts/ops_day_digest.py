#!/usr/bin/env python3
"""Build a factual digest of today's Hermes ops cron activity for the daily review job."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from ops_config import timezone_name as _tz_name
except Exception:
    def _tz_name():
        return 'America/Chicago'

try:
    from hermes_paths import brain_dir, dot_hermes, hermes_home
except Exception:
    import os as _os

    def hermes_home():
        env = _os.environ.get("HERMES_HOME", "").strip()
        if env:
            return Path(env)
        return Path.home() / ".local" / "share" / "hermes"

    def brain_dir():
        return hermes_home() / "brain"

    def dot_hermes():
        return Path.home() / ".hermes"

HERMES_HOME = hermes_home()
JOBS_FILE = HERMES_HOME / "cron" / "jobs.json"
OUTPUT_DIR = HERMES_HOME / "cron" / "output"
BRAIN_DIR = brain_dir()
ROADMAP_FILE = dot_hermes() / "roadmaps.json"
DESIGN_DOC = dot_hermes() / "OPS_DESIGN.md"
TZ = ZoneInfo(_tz_name())

# Expected behaviors for review (id -> expectations)
EXPECTATIONS = {
    "a1brain0600": "no_agent consolidate; refresh brain INDEX; telegram ok or silent",
    "41cb7755ae6d": "no_agent local health; write PIPELINES health; report failures",
    "026c0a4c82b7": "daily CI scan; wake on failures; weekend defer HITL Telegram",
    "b2prmon30m": "merge-on-green; APPROVAL Telegram weekdays only",
    "c3pm0930": "daily PM; weekend prefer agent items / defer HITL Telegram",
    "d4exec1014": "daily 20–30m; decompose; follow-ups; weekend defer HITL Telegram",
    "e5market184": "daily market/buyers; US sources; SILENT if no change",
    "g10humanq": "Needs-you backoff; quiet Sat/Sun",
    "f6ops2100": "daily review itself — skip self-grade except meta",
    "g7ui5m": "no_agent; keep roadmap UI :8888 up",
    "g8sync0615": "no_agent; sync HERMES_HOME ↔ ~/.hermes mirrors",
    "g9auditingest": "no_agent; ingest agent cron outputs into AUDIT",
    "g10humanq": "no_agent; Needs-you queue Telegram with exponential backoff; detect releases",
    # Optional modules (create cron jobs only when enabled in ops-config)
    "h12gcloud0730": "optional; no_agent GCP read-only scan; PIPELINES/COSTS; no autofix wake",
    "h11uilive23": "optional; UI/e2e GHA scan; optional local live checks behind HERMES_UI_LIVE_RUN",
}


def today_local() -> datetime:
    return datetime.now(TZ)


def is_today(ts: str | None) -> bool:
    if not ts:
        return False
    try:
        # handle offset ISO
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).date() == today_local().date()
    except Exception:
        return ts[:10] == today_local().strftime("%Y-%m-%d")


def load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    return data.get("jobs", [])


def summarize_outputs(job_id: str, day: str, limit: int = 6) -> list[dict]:
    folder = OUTPUT_DIR / job_id
    if not folder.is_dir():
        return []
    files = sorted(folder.glob(f"{day}_*.md"), key=lambda p: p.name, reverse=True)
    out = []
    for f in files[:limit]:
        text = f.read_text(encoding="utf-8", errors="replace")
        snippet = text[:1200]
        flags = []
        low = text.lower()
        for key in ("error", "fail", "traceback", "exception", "timed out", "chat not found"):
            if key in low:
                flags.append(key)
        out.append(
            {
                "file": str(f.name),
                "bytes": f.stat().st_size,
                "flags": flags,
                "snippet": snippet,
            }
        )
    return out


def human_queue() -> list[dict]:
    if not ROADMAP_FILE.exists():
        return []
    data = json.loads(ROADMAP_FILE.read_text(encoding="utf-8"))
    rows = []
    for proj, phases in data.items():
        for phase, items in phases.items():
            for item in items:
                if item.get("blocked") or item.get("owner") == "human":
                    rows.append(
                        {
                            "project": proj,
                            "phase": phase,
                            "name": item.get("name"),
                            "owner": item.get("owner"),
                            "blocked": item.get("blocked"),
                            "blocked_reason": item.get("blocked_reason", ""),
                        }
                    )
    return rows


def main() -> int:
    # Ensure agent cron outputs land in the audit trail even if the model forgot
    try:
        from audit_ingest_cron import main as ingest

        ingest()
    except Exception as exc:
        print(f"[audit ingest skipped: {exc}]", file=sys.stderr)

    day = today_local().strftime("%Y-%m-%d")
    stamp = today_local().strftime("%Y-%m-%d %H:%M %Z")
    jobs = load_jobs()

    # Primary SoT for evening review: structured AUDIT.jsonl scorecard
    try:
        from ops_audit import day_summary_text

        audit_scorecard = day_summary_text(day)
    except Exception as exc:
        audit_scorecard = f"## Audit day scorecard — {day}\n\n- (unavailable: {exc})"

    lines = [
        f"# Ops day digest — {day}",
        f"Generated: {stamp}",
        f"HERMES_HOME: {HERMES_HOME}",
        "",
        "## Design doc",
        f"- {DESIGN_DOC} (exists={DESIGN_DOC.exists()})",
        "",
        audit_scorecard,
        "",
        "## Job status (registry) — secondary",
        "",
    ]

    ran_today = 0
    failed = 0
    delivery_issues = 0

    for job in jobs:
        jid = job.get("id", "?")
        name = job.get("name", jid)
        status = job.get("last_status")
        last_run = job.get("last_run_at")
        err = job.get("last_error")
        deliv = job.get("last_delivery_error")
        provider = job.get("provider") or job.get("provider_snapshot") or "(unpinned)"
        model = job.get("model") or job.get("model_snapshot") or "(unpinned)"
        no_agent = bool(job.get("no_agent"))
        enabled = bool(job.get("enabled", True))
        today = is_today(last_run)
        if today:
            ran_today += 1
        if status and status != "ok" and today:
            failed += 1
        if deliv and today:
            delivery_issues += 1

        lines.append(f"### {name} (`{jid}`)")
        lines.append(f"- enabled={enabled} no_agent={no_agent} provider={provider} model={model}")
        lines.append(f"- schedule={job.get('schedule_display') or job.get('schedule')}")
        lines.append(f"- last_run_at={last_run} (today={today})")
        lines.append(f"- last_status={status} last_error={err}")
        lines.append(f"- last_delivery_error={deliv}")
        lines.append(f"- expectation: {EXPECTATIONS.get(jid, '(none documented)')}")
        outs = summarize_outputs(jid, day)
        lines.append(f"- outputs_today={len(list((OUTPUT_DIR / jid).glob(f'{day}_*.md'))) if (OUTPUT_DIR / jid).is_dir() else 0}")
        for o in outs[:3]:
            lines.append(f"  - {o['file']} flags={o['flags'] or 'none'}")
            if o["flags"]:
                # include short snippet when suspicious
                first = o["snippet"].splitlines()[:8]
                for ln in first:
                    lines.append(f"    > {ln[:200]}")
        lines.append("")

    hq = human_queue()
    lines.append("## Human / blocked roadmap queue")
    if not hq:
        lines.append("- (empty)")
    else:
        for r in hq[:30]:
            lines.append(
                f"- {r['project']}/{r['name']} phase={r['phase']} "
                f"owner={r['owner']} blocked={r['blocked']} reason={r['blocked_reason']}"
            )
    lines.append("")

    # Brain file sizes
    lines.append("## Brain files")
    if BRAIN_DIR.is_dir():
        for p in sorted(BRAIN_DIR.glob("*.md")):
            lines.append(f"- {p.name}: {p.stat().st_size} bytes")
    lines.append("")

    lines.append("## Counts")
    lines.append(f"- jobs_total={len(jobs)}")
    lines.append(f"- ran_today={ran_today}")
    lines.append(f"- failed_today={failed}")
    lines.append(f"- delivery_issues_today={delivery_issues}")
    lines.append(f"- human_queue={len(hq)}")
    lines.append("")
    lines.append("## Reviewer checklist")
    lines.append("1. Grade from **Audit day scorecard** first (missing events, blocked, errors).")
    lines.append("2. Did each job that ran meet its OPS_DESIGN expectation?")
    lines.append("3. Cost: any job using Copilot/Codex when Bonsai/no_agent would do?")
    lines.append("4. HITL: blocked audit human_gate + roadmap human_actions clear?")
    lines.append("5. Apply safe improvements; log them; Telegram concise day report.")
    lines.append("")

    text = "\n".join(lines)
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRAIN_DIR / f"DAILY_DIGEST_{day}.md"
    out_path.write_text(text, encoding="utf-8")

    # Also maintain latest pointer
    (BRAIN_DIR / "DAILY_DIGEST_LATEST.md").write_text(text, encoding="utf-8")

    print(text)
    print(f"\n[digest written: {out_path}]")
    # Always wake evening reviewer
    print(json.dumps({"wakeAgent": True}))
    try:
        from ops_audit import append_event

        append_event(
            job_id="f6ops2100",
            name="Daily ops review (digest)",
            status="ok",
            summary=(
                f"Wrote day digest; audit SoT + registry; "
                f"failed_registry={failed} human_queue={len(hq)}"
            ),
            artifacts=[str(out_path), str(BRAIN_DIR / "DAILY_DIGEST_LATEST.md")],
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
