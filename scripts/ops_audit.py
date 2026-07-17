#!/usr/bin/env python3
"""Append / query structured ops audit events (JSONL + daily MD).

Usage:
  python ops_audit.py append --job a1brain0600 --name "Brain consolidate" \\
    --status ok --summary "Refreshed INDEX" --detail "..." \\
    --repo your-org/your-repo --pr-url https://... --roadmap-item "match/case"

  python ops_audit.py recent [--job ID] [--status blocked] [--day YYYY-MM-DD] [-n 10]
  python ops_audit.py day-summary [--day YYYY-MM-DD]
  python ops_audit.py tail [-n 20]
  python ops_audit.py today
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from ops_config import timezone_name as _tz_name
except Exception:
    def _tz_name():
        return 'America/Chicago'

TZ = ZoneInfo(_tz_name())
HERMES_HOME = Path(
    os.environ.get("HERMES_HOME", Path(os.environ.get("LOCALAPPDATA", "")) / "hermes")
)
BRAIN = HERMES_HOME / "brain"
JSONL = BRAIN / "AUDIT.jsonl"
MD_LATEST = BRAIN / "AUDIT.md"

# Jobs that should leave a trail when they fire (for day-summary gaps)
CORE_JOB_IDS = {
    "a1brain0600",
    "41cb7755ae6d",
    "026c0a4c82b7",
    "b2prmon30m",
    "c3pm0930",
    "d4exec1014",
    "e5market184",
    "f6ops2100",
    "g8sync0615",
}


def _now() -> datetime:
    return datetime.now(TZ)


def _day_md(day: str) -> Path:
    return BRAIN / f"AUDIT_{day}.md"


def load_events() -> list[dict]:
    if not JSONL.exists():
        return []
    out: list[dict] = []
    for ln in JSONL.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def query_events(
    *,
    job_id: str | None = None,
    status: str | None = None,
    day: str | None = None,
    repo: str | None = None,
    n: int | None = None,
) -> list[dict]:
    events = load_events()
    if job_id:
        events = [e for e in events if e.get("job_id") == job_id]
    if status:
        events = [e for e in events if e.get("status") == status]
    if day:
        events = [e for e in events if e.get("day") == day]
    if repo:
        r = repo.lower()
        events = [
            e
            for e in events
            if (e.get("repo") or "").lower() == r
            or r in (e.get("repo") or "").lower()
        ]
    if n is not None:
        events = events[-n:]
    return events


def append_event(
    *,
    job_id: str,
    name: str = "",
    status: str = "ok",
    summary: str,
    detail: str = "",
    artifacts: list[str] | None = None,
    repo: str = "",
    pr_url: str = "",
    roadmap_item: str = "",
    human_gate: str = "",
    model: str = "",
    extra: dict | None = None,
) -> dict:
    BRAIN.mkdir(parents=True, exist_ok=True)
    now = _now()
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    event: dict = {
        "ts": now.isoformat(),
        "day": day,
        "job_id": job_id,
        "name": name or job_id,
        "status": status,
        "summary": summary.strip(),
        "detail": (detail or "").strip(),
        "artifacts": [a for a in (artifacts or []) if a],
    }
    if repo:
        event["repo"] = repo.strip()
    if pr_url:
        event["pr_url"] = pr_url.strip()
    if roadmap_item:
        event["roadmap_item"] = roadmap_item.strip()
    if human_gate:
        event["human_gate"] = human_gate.strip()
    if model:
        event["model"] = model.strip()
    if extra:
        event["extra"] = extra

    with JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    lines = [
        f"### {stamp} — `{event['job_id']}` ({event['name']}) — **{status}**",
        f"- {event['summary']}",
    ]
    meta = []
    if event.get("repo"):
        meta.append(f"repo={event['repo']}")
    if event.get("roadmap_item"):
        meta.append(f"item={event['roadmap_item']}")
    if event.get("pr_url"):
        meta.append(f"pr={event['pr_url']}")
    if event.get("human_gate"):
        meta.append(f"gate={event['human_gate']}")
    if event.get("model"):
        meta.append(f"model={event['model']}")
    if meta:
        lines.append(f"- {' | '.join(meta)}")
    if event["detail"]:
        for ln in event["detail"].splitlines()[:12]:
            lines.append(f"  - {ln}")
    if event["artifacts"]:
        lines.append("- artifacts:")
        for a in event["artifacts"][:10]:
            lines.append(f"  - {a}")
    lines.append("")
    block = "\n".join(lines)

    day_path = _day_md(day)
    if not day_path.exists():
        day_path.write_text(f"# Ops audit — {day}\n\n", encoding="utf-8")
    with day_path.open("a", encoding="utf-8") as f:
        f.write(block)

    MD_LATEST.write_text(day_path.read_text(encoding="utf-8"), encoding="utf-8")
    return event


def format_event_brief(e: dict) -> str:
    parts = [
        f"- `{e.get('ts', '')[:19]}` `{e.get('job_id')}` **{e.get('status')}** — {e.get('summary', '')[:200]}"
    ]
    bits = []
    if e.get("repo"):
        bits.append(e["repo"])
    if e.get("roadmap_item"):
        bits.append(e["roadmap_item"])
    if e.get("pr_url"):
        bits.append(e["pr_url"])
    if e.get("human_gate"):
        bits.append(e["human_gate"])
    if bits:
        parts.append(f"  - {' | '.join(bits)}")
    detail = (e.get("detail") or "").strip()
    if detail:
        first = detail.splitlines()[0][:160]
        parts.append(f"  - {first}")
    return "\n".join(parts)


def day_summary_text(day: str | None = None) -> str:
    day = day or _now().strftime("%Y-%m-%d")
    events = query_events(day=day)
    by_job: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_job[e.get("job_id", "?")].append(e)

    status_counts = Counter(e.get("status", "?") for e in events)
    blocked = [e for e in events if e.get("status") == "blocked"]
    # also surface recent open blocks from prior days (last 20 blocked overall, not resolved by later ok same job+item)
    recent_blocks = [
        e for e in load_events() if e.get("status") == "blocked"
    ][-15:]

    lines = [
        f"## Audit day scorecard — {day}",
        "",
        f"- events_today={len(events)}",
        f"- by_status: {dict(status_counts) if status_counts else '{}'}",
        "",
        "### Per job (latest today)",
    ]
    if not by_job:
        lines.append("- (no audit events today)")
    else:
        for jid in sorted(by_job):
            evs = by_job[jid]
            last = evs[-1]
            lines.append(
                f"- `{jid}` ({last.get('name', jid)}): n={len(evs)} "
                f"latest=**{last.get('status')}** — {last.get('summary', '')[:160]}"
            )
            if last.get("repo") or last.get("roadmap_item") or last.get("pr_url"):
                meta = " | ".join(
                    x
                    for x in (
                        last.get("repo"),
                        last.get("roadmap_item"),
                        last.get("pr_url"),
                    )
                    if x
                )
                lines.append(f"  - {meta}")

    lines.append("")
    lines.append("### Blocked today")
    if not blocked:
        lines.append("- (none)")
    else:
        for e in blocked:
            lines.append(format_event_brief(e))

    lines.append("")
    lines.append("### Recent blocked (incl. prior days — resume these)")
    if not recent_blocks:
        lines.append("- (none)")
    else:
        for e in recent_blocks:
            lines.append(format_event_brief(e))

    # Jobs with no audit today (informational — weekday schedules vary)
    missing = sorted(CORE_JOB_IDS - set(by_job))
    lines.append("")
    lines.append("### Core jobs with no audit event today")
    if not missing:
        lines.append("- (all core jobs have ≥1 event)")
    else:
        for jid in missing:
            lines.append(f"- `{jid}`")

    lines.append("")
    lines.append(
        "Grade primarily from this scorecard + OPS_DESIGN expectations; "
        "use registry/output sections below as secondary evidence."
    )
    return "\n".join(lines)


def cmd_append(args: argparse.Namespace) -> int:
    arts = []
    if args.artifact:
        arts.extend(args.artifact)
    if args.artifacts:
        arts.extend([x.strip() for x in args.artifacts.split(",") if x.strip()])
    # Convenience: PR URL often also belongs in artifacts
    if args.pr_url and args.pr_url not in arts:
        arts.append(args.pr_url)
    ev = append_event(
        job_id=args.job,
        name=args.name or "",
        status=args.status,
        summary=args.summary,
        detail=args.detail or "",
        artifacts=arts,
        repo=args.repo or "",
        pr_url=args.pr_url or "",
        roadmap_item=args.roadmap_item or "",
        human_gate=args.human_gate or "",
        model=args.model or "",
    )
    print(f"audit appended: {ev['ts']} {ev['job_id']} {ev['status']}")
    return 0


def cmd_tail(args: argparse.Namespace) -> int:
    events = query_events(n=args.n)
    if not events:
        print("(no AUDIT.jsonl yet)")
        return 0
    for e in events:
        print(json.dumps(e, ensure_ascii=False))
    return 0


def cmd_today(_: argparse.Namespace) -> int:
    day = _now().strftime("%Y-%m-%d")
    path = _day_md(day)
    if path.exists():
        print(path.read_text(encoding="utf-8"))
    elif MD_LATEST.exists():
        print(MD_LATEST.read_text(encoding="utf-8"))
    else:
        print(f"(no audit for {day})")
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    events = query_events(
        job_id=args.job,
        status=args.status,
        day=args.day,
        repo=args.repo,
        n=args.n,
    )
    if not events:
        print("(no matching audit events)")
        return 0
    if args.json:
        for e in events:
            print(json.dumps(e, ensure_ascii=False))
        return 0
    print(f"# Audit recent (n={len(events)})")
    for e in events:
        print(format_event_brief(e))
    return 0


def cmd_day_summary(args: argparse.Namespace) -> int:
    print(day_summary_text(args.day))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Hermes ops audit trail")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append", help="Append one audit event")
    a.add_argument("--job", required=True, help="Cron job id")
    a.add_argument("--name", default="", help="Human job name")
    a.add_argument(
        "--status",
        default="ok",
        choices=["ok", "error", "partial", "silent", "blocked", "skipped"],
    )
    a.add_argument("--summary", required=True, help="One-line what happened")
    a.add_argument("--detail", default="", help="Optional multi-line detail")
    a.add_argument("--artifact", action="append", default=[], help="Repeatable path/URL")
    a.add_argument("--artifacts", default="", help="Comma-separated paths/URLs")
    a.add_argument("--repo", default="", help="e.g. your-org/your-repo")
    a.add_argument("--pr-url", default="", dest="pr_url", help="PR URL")
    a.add_argument("--roadmap-item", default="", dest="roadmap_item", help="Roadmap item name")
    a.add_argument(
        "--human-gate",
        default="",
        dest="human_gate",
        help="ACTION:... or APPROVAL:...",
    )
    a.add_argument("--model", default="", help="Model used for this run")
    a.set_defaults(func=cmd_append)

    t = sub.add_parser("tail", help="Print last N JSONL events")
    t.add_argument("-n", type=int, default=20)
    t.set_defaults(func=cmd_tail)

    d = sub.add_parser("today", help="Print today's human-readable audit")
    d.set_defaults(func=cmd_today)

    r = sub.add_parser("recent", help="Query recent events (agents: read before acting)")
    r.add_argument("--job", default=None, help="Filter job id")
    r.add_argument("--status", default=None, help="Filter status e.g. blocked")
    r.add_argument("--day", default=None, help="YYYY-MM-DD")
    r.add_argument("--repo", default=None, help="Filter repo")
    r.add_argument("-n", type=int, default=10)
    r.add_argument("--json", action="store_true", help="Raw JSONL lines")
    r.set_defaults(func=cmd_recent)

    s = sub.add_parser("day-summary", help="Scorecard for a day (digest SoT)")
    s.add_argument("--day", default=None, help="YYYY-MM-DD (default today)")
    s.set_defaults(func=cmd_day_summary)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
