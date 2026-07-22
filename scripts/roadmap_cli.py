#!/usr/bin/env python3
"""Roadmap CLI — manage project roadmaps with add/list/move/remove/edit/show/stats."""

from __future__ import annotations

import argparse
import json
import os
import sys

from roadmap_history import (
    append_activity,
    normalize_item as normalize_history_item,
    relate_items,
)

ROADMAP_FILE = os.path.expanduser("~/.hermes/roadmaps.json")
PHASES = ["In Progress", "Upcoming", "Backlog", "Done"]
OWNERS = ("agent", "human")
try:
    from ops_config import product_names
    DEFAULT_PROJECTS = product_names()
except Exception:
    DEFAULT_PROJECTS = ['example-app']


def normalize_item(item: dict, *, history_migration: bool = True) -> bool:
    """Ensure owner, human, identity, history, and relationship fields exist."""
    changed = False
    if "owner" not in item or item.get("owner") not in OWNERS:
        item["owner"] = "agent"
        changed = True
    if "human_actions" not in item:
        item["human_actions"] = []
        changed = True
    elif isinstance(item["human_actions"], str):
        item["human_actions"] = [item["human_actions"]] if item["human_actions"].strip() else []
        changed = True
    if "blocked" not in item:
        item["blocked"] = False
        changed = True
    if "blocked_reason" not in item:
        item["blocked_reason"] = ""
        changed = True
    if normalize_history_item(item, migration_event=history_migration):
        changed = True
    return changed


def load():
    if os.path.exists(ROADMAP_FILE):
        with open(ROADMAP_FILE, encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = {}
    changed = False
    for name in DEFAULT_PROJECTS:
        if name not in d:
            d[name] = {p: [] for p in PHASES}
            changed = True
        else:
            for phase in PHASES:
                if phase not in d[name]:
                    d[name][phase] = []
                    changed = True
    for _proj, phases in d.items():
        for phase in PHASES:
            for item in phases.get(phase, []):
                if normalize_item(item):
                    changed = True
    if changed:
        save(d)
    return d


def save(d):
    os.makedirs(os.path.dirname(ROADMAP_FILE), exist_ok=True)
    with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.write("\n")


def phase_badge(phase):
    return {"In Progress": "[IP]", "Upcoming": "[UP]", "Backlog": "[BL]", "Done": "[DN]"}[phase]


def priority_emoji(p):
    return {1: "P1", 2: "P2", 3: "P3"}.get(p, "P3")


def owner_label(item):
    owner = item.get("owner", "agent")
    blocked = item.get("blocked")
    if owner == "human":
        return "HUMAN" + (" BLOCKED" if blocked else "")
    return "AGENT" + (" BLOCKED" if blocked else "")


def show_all(d):
    for name, phases in sorted(d.items()):
        print(f"\n{'-' * 60}")
        print(f"  {name}")
        print(f"{'-' * 60}")
        total = 0
        for phase in PHASES:
            items = phases.get(phase, [])
            print(f"\n  {phase_badge(phase)} {phase} ({len(items)})")
            for i, item in enumerate(items, 1):
                due = item.get("date", "-") or "-"
                tags = " ".join(f"#{t}" for t in item.get("tags", []))
                notes = item.get("notes", "")
                print(
                    f"    {i:2d}. {priority_emoji(item.get('priority', 3))} "
                    f"[{owner_label(item)}] {item['name']}"
                )
                print(f"       Due: {due} | Tags: {tags}")
                if notes:
                    print(f"       Notes: {notes}")
                if item.get("blocked_reason"):
                    print(f"       Blocked: {item['blocked_reason']}")
                actions = item.get("human_actions") or []
                if actions:
                    print("       Human actions:")
                    for a in actions:
                        print(f"         - {a}")
            total += len(items)
        print(f"\n  Total: {total} item(s)\n")


def show_product(d, name):
    if name not in d:
        print(f"  Project '{name}' not found.")
        return
    show_all({name: d[name]})


def add_item(d, name, item):
    if name not in d:
        d[name] = {p: [] for p in PHASES}
    phase = item.pop("phase", "Backlog")
    if phase not in d[name]:
        d[name][phase] = []
    normalize_item(item, history_migration=False)
    append_activity(item, "Item created", kind="created", actor="agent")
    d[name][phase].append(item)
    save(d)
    print(f"  Added: {item['name']} → {name}/{phase} owner={item['owner']}")


def list_all(d):
    for name, phases in sorted(d.items()):
        total = sum(len(v) for v in phases.values())
        human = sum(
            1
            for ph in PHASES
            for it in phases.get(ph, [])
            if it.get("owner") == "human"
        )
        print(f"{name:20s} | {total:3d} items | {human:2d} human")


def find_item(d, name, item_name):
    for phase in PHASES:
        for i, item in enumerate(d.get(name, {}).get(phase, [])):
            if item["name"] == item_name:
                return phase, i, item
    return None, None, None


def move_item(d, name, item_name, new_phase):
    if name not in d:
        print(f"  Project '{name}' not found.")
        return
    if new_phase not in PHASES:
        print(f"  Invalid phase: {new_phase}")
        return
    phase, idx, item = find_item(d, name, item_name)
    if item is None:
        print(f"  Item '{item_name}' not found in {name}")
        return
    d[name][phase].pop(idx)
    d[name][new_phase].append(item)
    append_activity(item, f"phase: {phase} → {new_phase}", kind="moved", actor="agent")
    save(d)
    print(f"  Moved: {item_name} → {name}/{new_phase}")


def remove_item(d, name, item_name):
    phase, idx, item = find_item(d, name, item_name)
    if item is None:
        print(f"  Item '{item_name}' not found in {name}")
        return
    d[name][phase].pop(idx)
    save(d)
    print(f"  Removed: {item_name} from {name}/{phase}")


def edit_item(d, name, item_name, **changes):
    phase, idx, item = find_item(d, name, item_name)
    if item is None:
        print(f"  Item '{item_name}' not found in {name}")
        return
    differences = []
    for k, v in changes.items():
        if v is not None:
            if item.get(k) != v:
                differences.append(f"{k}: {item.get(k)!r} → {v!r}")
            item[k] = v
    normalize_item(item)
    if differences:
        append_activity(item, "; ".join(differences), kind="updated", actor="agent")
    save(d)
    print(f"  Updated: {item_name} in {name}/{phase} owner={item.get('owner')}")


def log_item(d, name, item_name, message, kind="progress", actor="agent"):
    phase, _idx, item = find_item(d, name, item_name)
    if item is None:
        print(f"  Item '{item_name}' not found in {name}", file=sys.stderr)
        return False
    append_activity(item, message, kind=kind, actor=actor)
    save(d)
    print(f"  Logged: {item_name} in {name}/{phase}")
    return True


def relate_item(d, name, item_name, related_project, related_item, relation, actor="agent"):
    try:
        relate_items(
            d,
            name,
            item_name,
            related_project,
            related_item,
            relation=relation,
            actor=actor,
        )
    except (KeyError, ValueError) as exc:
        print(f"  {exc}", file=sys.stderr)
        return False
    save(d)
    print(f"  Related: {name}/{item_name} {relation} {related_project}/{related_item}")
    return True


def stats(d):
    for name, phases in sorted(d.items()):
        print(f"\n  {name}:")
        for phase in PHASES:
            items = phases.get(phase, [])
            human = sum(1 for it in items if it.get("owner") == "human")
            blocked = sum(1 for it in items if it.get("blocked"))
            print(f"    {phase:15s} {len(items):3d} (human={human} blocked={blocked})")
        total = sum(len(v) for v in phases.values())
        print(f"    {'-' * 25}")
        print(f"    {'TOTAL':15s} {total}")
    print()


def parse_actions(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return []
    if "|" in raw:
        return [a.strip() for a in raw.split("|") if a.strip()]
    return [a.strip() for a in raw.split(";") if a.strip()]


def main():
    p = argparse.ArgumentParser(description="Roadmap CLI")
    p.add_argument(
        "cmd",
        choices=["add", "list", "show", "move", "remove", "edit", "log", "relate", "stats"],
        help="Command",
    )
    p.add_argument("--project", "-p", help="Project name")
    p.add_argument("--item", "-i", help="Item name")
    p.add_argument("--phase", help="Phase for add: In Progress|Upcoming|Backlog|Done")
    p.add_argument("--new-phase", help="Destination phase for move")
    p.add_argument("--priority", type=int, help="Priority (1-3)")
    p.add_argument("--date", help="Due date")
    p.add_argument("--tags", help="Tags (comma-separated)")
    p.add_argument("--notes", help="Notes")
    p.add_argument("--owner", choices=list(OWNERS), help="Who does the work: agent|human")
    p.add_argument(
        "--human-actions",
        help="Exact steps for the human, separated by | or ;",
    )
    p.add_argument("--blocked", choices=["true", "false"], help="Mark item blocked")
    p.add_argument("--blocked-reason", help="Why work is waiting on a human")
    p.add_argument("--message", help="Activity message for log")
    p.add_argument("--kind", default="progress", help="Activity kind for log")
    p.add_argument("--actor", default="agent", help="Activity actor")
    p.add_argument("--related-project", help="Project containing the related item")
    p.add_argument("--related-item", help="Related item name or id")
    p.add_argument(
        "--relation",
        default="related",
        help="Relationship, e.g. blocks, parent of, depends on",
    )
    args = p.parse_args()
    d = load()

    if args.cmd in ("add", "move", "remove", "edit", "log", "relate") and not args.project:
        print("  --project is required for this command", file=sys.stderr)
        sys.exit(2)
    if args.cmd in ("add", "move", "remove", "edit", "log", "relate") and not args.item:
        print("  --item is required for this command", file=sys.stderr)
        sys.exit(2)

    if args.cmd == "add":
        phase = args.phase or "Backlog"
        owner = args.owner or "agent"
        actions = parse_actions(args.human_actions) or []
        blocked = args.blocked == "true" if args.blocked else (owner == "human" and bool(actions))
        item = {
            "name": args.item,
            "phase": phase,
            "priority": args.priority or 3,
            "date": args.date or "",
            "tags": [t.strip() for t in args.tags.split(",")] if args.tags else [],
            "notes": args.notes or "",
            "owner": owner,
            "human_actions": actions,
            "blocked": blocked,
            "blocked_reason": args.blocked_reason or "",
        }
        add_item(d, args.project, item)
    elif args.cmd == "list":
        list_all(d)
    elif args.cmd == "show":
        if args.project:
            show_product(d, args.project)
        else:
            show_all(d)
    elif args.cmd == "move":
        move_item(d, args.project, args.item, args.new_phase or "In Progress")
    elif args.cmd == "remove":
        remove_item(d, args.project, args.item)
    elif args.cmd == "edit":
        edits = {}
        if args.priority is not None:
            edits["priority"] = args.priority
        if args.date:
            edits["date"] = args.date
        if args.tags:
            edits["tags"] = [t.strip() for t in args.tags.split(",")]
        if args.notes is not None:
            edits["notes"] = args.notes
        if args.owner:
            edits["owner"] = args.owner
        actions = parse_actions(args.human_actions)
        if actions is not None:
            edits["human_actions"] = actions
        if args.blocked is not None:
            edits["blocked"] = args.blocked == "true"
        if args.blocked_reason is not None:
            edits["blocked_reason"] = args.blocked_reason
        edit_item(d, args.project, args.item, **edits)
    elif args.cmd == "log":
        if not args.message:
            p.error("--message is required for log")
        if not log_item(d, args.project, args.item, args.message, args.kind, args.actor):
            sys.exit(1)
    elif args.cmd == "relate":
        if not args.related_item:
            p.error("--related-item is required for relate")
        if not relate_item(
            d,
            args.project,
            args.item,
            args.related_project or args.project,
            args.related_item,
            args.relation,
            args.actor,
        ):
            sys.exit(1)
    elif args.cmd == "stats":
        stats(d)


if __name__ == "__main__":
    main()
