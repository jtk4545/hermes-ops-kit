#!/usr/bin/env python3
"""Format human-blocked / human-owned roadmap items for Telegram delivery."""

from __future__ import annotations

import argparse
import json
import os
import sys

ROADMAP_FILE = os.path.expanduser("~/.hermes/roadmaps.json")
PHASES = ["In Progress", "Upcoming", "Backlog", "Done"]


def kind_of(row: dict) -> str:
    reason = (row.get("blocked_reason") or "").strip()
    upper = reason.upper()
    if upper.startswith("APPROVAL:"):
        return "APPROVAL"
    if upper.startswith("ACTION:"):
        return "ACTION"
    if row.get("blocked"):
        return "BLOCKED"
    return "HUMAN"


def collect(project: str | None = None, include_unblocked_human: bool = True) -> list[dict]:
    with open(ROADMAP_FILE, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for proj, phases in sorted(data.items()):
        if project and proj != project:
            continue
        for phase in PHASES:
            for item in phases.get(phase, []):
                owner = item.get("owner", "agent")
                blocked = bool(item.get("blocked"))
                if blocked:
                    out.append({"project": proj, "phase": phase, **item})
                    continue
                if (
                    include_unblocked_human
                    and owner == "human"
                    and phase in ("In Progress", "Upcoming")
                ):
                    out.append({"project": proj, "phase": phase, **item})
    return out


def format_item(row: dict) -> str:
    kind = kind_of(row)
    lines = [
        f"{kind} NEEDED — {row['project']} / {row.get('name')}",
        f"Phase: {row.get('phase')} | Priority: P{row.get('priority', 3)} | Owner: {row.get('owner', 'human')}",
    ]
    if row.get("blocked_reason"):
        lines.append(f"Why: {row['blocked_reason']}")
    if row.get("notes"):
        lines.append(f"Context / materials: {row['notes']}")
    actions = row.get("human_actions") or []
    if kind == "APPROVAL":
        lines.append("Reply with exactly one of: yes | no | hold")
        if actions:
            lines.append("Details:")
            for i, a in enumerate(actions, 1):
                lines.append(f"  {i}. {a}")
    else:
        if actions:
            lines.append("Exact actions for you:")
            for i, a in enumerate(actions, 1):
                lines.append(f"  {i}. {a}")
        else:
            lines.append("Exact actions for you: (none listed — reply with what you did)")
    tags = row.get("tags") or []
    if tags:
        lines.append("Tags: " + ", ".join(tags))
    lines.append(f"UI: http://127.0.0.1:8888/ → Needs you → I did this — release to agent")
    lines.append(
        "After release: weekday executor (10:00 / 14:00) resumes; "
        "human_queue_watch pings with exponential backoff until then."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument(
        "--blocked-only",
        action="store_true",
        help="Only items with blocked=true",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    rows = collect(args.project or None, include_unblocked_human=not args.blocked_only)
    if args.blocked_only:
        rows = [r for r in rows if r.get("blocked")]
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0
    if not rows:
        return 0
    print("=== Human action / approval queue ===\n")
    for i, row in enumerate(rows, 1):
        print(format_item(row))
        if i < len(rows):
            print("\n---\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
