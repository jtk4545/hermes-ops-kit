#!/usr/bin/env python
"""Persist executor item context and append failure-safe execution logs."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from hermes_paths import roadmap_file
from roadmap_history import append_activity, normalize_item

HOME = Path.home() / ".hermes"
ROADMAP = roadmap_file()
STATE = HOME / "roadmap_executor_state.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stamp():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def find_item(data, project, item):
    for phase, items in data.get(project, {}).items():
        for entry in items:
            if entry.get("name") == item:
                return phase, entry
    raise SystemExit(f"Roadmap item not found: {project} / {item}")


def start(args):
    # Validate before recording; this prevents an error handler writing to an arbitrary item.
    data = load(ROADMAP)
    _phase, entry = find_item(data, args.project, args.item)
    normalize_item(entry)
    append_activity(
        entry,
        f"Executor run started — job: {args.job}; model: {args.model}",
        kind="execution_started",
        actor=args.job,
    )
    save(ROADMAP, data)
    state = load(STATE)
    state[args.job] = {
        "project": args.project,
        "item": args.item,
        "model": args.model,
        "started_at": stamp(),
    }
    save(STATE, state)
    print(f"Tracking {args.project} / {args.item} for {args.job}")


def quota_stop(args):
    state = load(STATE).get(args.job)
    if not state:
        print(f"No active roadmap item recorded for {args.job}; nothing to log")
        return
    data = load(ROADMAP)
    phase, entry = find_item(data, state["project"], state["item"])
    normalize_item(entry)
    summary = (
        f"STOPPED — provider rate limit (429); job: {args.job}; "
        f"model: {state.get('model', 'unknown')}; phase: {phase}. "
        "No further work started; resume this item when quota resets."
    )
    append_activity(
        entry,
        summary,
        kind="quota_stopped",
        actor=args.job,
        details=f"Error: {args.error[:500]}",
    )
    save(ROADMAP, data)
    print(f"Logged 429 stop to {state['project']} / {state['item']}")


p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("start")
a.add_argument("--job", required=True)
a.add_argument("--project", required=True)
a.add_argument("--item", required=True)
a.add_argument("--model", required=True)
a.set_defaults(func=start)
b = sub.add_parser("quota-stop")
b.add_argument("--job", required=True)
b.add_argument("--error", required=True)
b.set_defaults(func=quota_stop)
args = p.parse_args()
args.func(args)
