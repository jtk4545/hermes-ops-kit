#!/usr/bin/env python3
"""Watch roadmap "Needs you" queue: Telegram with exponential backoff + resolve detect.

Populates/keeps the UI panel honest by nagging until human_actions are listed and
the item is released (blocked=false, owner=agent) via UI/CLI.

Silent when nothing is due. deliver=telegram on the cron job.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from ops_config import timezone_name as _tz_name
except Exception:
    def _tz_name():
        return 'America/Chicago'

sys.path.insert(0, str(Path(__file__).resolve().parent))

from human_block_format import collect, format_item, kind_of  # noqa: E402
from ops_audit import append_event  # noqa: E402
from brain_paths import BRAIN_DIR  # noqa: E402
from weekend_policy import is_weekend  # noqa: E402

TZ = ZoneInfo(_tz_name())
STATE_FILE = BRAIN_DIR / "HUMAN_QUEUE_STATE.json"
UI_URL = "http://127.0.0.1:8888/"
JOB_ID = "g10humanq"

# Minutes to wait after alert N (0-based) before the next Telegram
# 1st: immediate, then 30m → 1h → 2h → 4h → 8h → 24h (cap)
BACKOFF_MINUTES = [0, 30, 60, 120, 240, 480, 1440]


def _now() -> datetime:
    return datetime.now(TZ)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    except ValueError:
        return None


def item_key(row: dict) -> str:
    return f"{row['project']}::{row.get('name', '')}"


def load_state() -> dict:
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"items": {}, "resolved": {}}


def save_state(state: dict) -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def next_delay_minutes(alert_count: int) -> int:
    idx = min(max(alert_count, 0), len(BACKOFF_MINUTES) - 1)
    return BACKOFF_MINUTES[idx]


def is_due(entry: dict, now: datetime) -> bool:
    nxt = _parse(entry.get("next_alert_at"))
    if nxt is None:
        return True
    return now >= nxt


def format_compact(row: dict, alert_count: int, next_wait: int) -> str:
    kind = kind_of(row)
    why = (row.get("blocked_reason") or "").strip() or "(no reason — edit item)"
    acts = row.get("human_actions") or []
    lines = [
        f"{kind} REMINDER ({alert_count + 1}) — {row['project']} / {row.get('name')}",
        f"Why: {why}",
        f"UI: {UI_URL}  →  Needs you  →  I did this — release to agent",
    ]
    if acts:
        lines.append("Steps:")
        for i, a in enumerate(acts[:8], 1):
            lines.append(f"  {i}. {a}")
    else:
        lines.append(
            "⚠️ No steps on this item — edit in UI and add short human_actions "
            "(one verb per line) so the Needs you panel is actionable."
        )
    lines.append(
        f"Next ping if still open: ~{next_wait}m (exponential backoff, max 24h)."
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Human queue watch + Telegram backoff")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Ignore backoff; alert all open items (testing)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would alert; do not update state or audit",
    )
    args = ap.parse_args()

    now = _now()
    weekend = is_weekend(now)
    state = load_state()
    open_items: dict = state.setdefault("items", {})
    resolved_log: dict = state.setdefault("resolved", {})

    rows = collect(None, include_unblocked_human=True)
    # Skip Done-phase humans if any slipped in
    rows = [r for r in rows if r.get("phase") != "Done"]
    current_keys = {item_key(r) for r in rows}
    by_key = {item_key(r): r for r in rows}

    messages: list[str] = []
    newly_resolved: list[str] = []
    alerts_sent = 0
    missing_steps = 0

    # Detect resolutions: were open, now gone from needs-you queue
    for key, entry in list(open_items.items()):
        if key in current_keys:
            continue
        newly_resolved.append(key)
        resolved_log[key] = {
            "resolved_at": now.isoformat(),
            "was": {
                "reason": entry.get("reason"),
                "first_seen": entry.get("first_seen"),
                "alert_count": entry.get("alert_count", 0),
            },
        }
        del open_items[key]
        # Resolution is good news — audit only, no Telegram (user already acted)

    # Track + alert open items
    for key, row in by_key.items():
        acts = row.get("human_actions") or []
        if not acts:
            missing_steps += 1
        entry = open_items.get(key)
        if not entry:
            entry = {
                "first_seen": now.isoformat(),
                "alert_count": 0,
                "last_alert_at": None,
                "next_alert_at": None,
                "reason": (row.get("blocked_reason") or "")[:300],
                "project": row["project"],
                "name": row.get("name"),
            }
            open_items[key] = entry

        entry["reason"] = (row.get("blocked_reason") or entry.get("reason") or "")[:300]
        entry["last_seen"] = now.isoformat()
        entry["has_steps"] = bool(acts)
        entry["kind"] = kind_of(row)

        due = args.force or is_due(entry, now)
        if not due:
            continue

        # Weekends: track queue + resolutions, but do not Telegram-nag humans
        if weekend and not args.force:
            if not args.dry_run:
                # Push next attempt to Monday morning-ish without counting as a ping
                entry["next_alert_at"] = (
                    now + timedelta(hours=12)
                ).isoformat()
                entry["weekend_suppressed"] = True
            continue

        count = int(entry.get("alert_count") or 0)
        # delay AFTER this alert before the next one
        next_wait = next_delay_minutes(min(count + 1, len(BACKOFF_MINUTES) - 1))
        messages.append(format_compact(row, count, next_wait))
        alerts_sent += 1

        if not args.dry_run:
            entry["alert_count"] = count + 1
            entry["last_alert_at"] = now.isoformat()
            entry["next_alert_at"] = (now + timedelta(minutes=next_wait)).isoformat()
            entry.pop("weekend_suppressed", None)

    # Prune old resolved log (keep 60 days)
    cutoff = now - timedelta(days=60)
    for key, meta in list(resolved_log.items()):
        ts = _parse(meta.get("resolved_at") if isinstance(meta, dict) else None)
        if ts and ts < cutoff:
            del resolved_log[key]

    if not args.dry_run:
        save_state(state)

    if not messages:
        # Silent — nothing due
        if not args.dry_run:
            try:
                append_event(
                    job_id=JOB_ID,
                    name="Human queue watch",
                    status="silent",
                    summary=f"Open={len(current_keys)}; nothing due for Telegram",
                    extra={
                        "open": len(current_keys),
                        "missing_steps": missing_steps,
                    },
                )
            except Exception:
                pass
        return 0

    # Telegram body
    header = [
        f"=== Human queue ({now.strftime('%Y-%m-%d %H:%M %Z')}) ===",
        f"Open: {len(current_keys)} · Alerts this run: {alerts_sent} · "
        f"Resolved this run: {len(newly_resolved)}",
        f"Panel: {UI_URL}",
        "",
    ]
    body = "\n\n---\n\n".join(messages)
    print("\n".join(header) + body)

    if not args.dry_run:
        status = "ok"
        if missing_steps and alerts_sent:
            status = "partial"
        try:
            append_event(
                job_id=JOB_ID,
                name="Human queue watch",
                status=status,
                summary=(
                    f"Telegram: {alerts_sent} reminder(s), "
                    f"{len(newly_resolved)} resolved; open={len(current_keys)}"
                ),
                detail="\n".join(
                    f"{k}: alerts={open_items.get(k, {}).get('alert_count')}"
                    for k in sorted(current_keys)
                )[:800],
                artifacts=[UI_URL, str(STATE_FILE)],
            )
        except Exception as exc:
            print(f"[audit skipped: {exc}]", file=sys.stderr)

        # Wake executor path when something was released to agent
        if newly_resolved:
            print(json.dumps({"wakeAgent": False, "resolved": newly_resolved}))
            # Note: no agent on this job; executor cron picks up on schedule.
            # wakeAgent false — this is no_agent. Resolution notice already Telegrams.

    return 0


if __name__ == "__main__":
    sys.exit(main())
