#!/usr/bin/env python3
"""Shared roadmap item identity, activity history, and relationship helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Iterable

PHASES = ("In Progress", "Upcoming", "Backlog", "Done")
INVERSE_RELATIONS = {
    "blocks": "blocked by",
    "blocked by": "blocks",
    "parent of": "child of",
    "child of": "parent of",
    "depends on": "dependency of",
    "dependency of": "depends on",
    "related": "related",
}
IGNORED_DIFF_FIELDS = {"id", "activity", "created_at", "updated_at"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iter_items(data: dict) -> Iterable[tuple[str, str, dict]]:
    for project, phases in data.items():
        if not isinstance(phases, dict):
            continue
        for phase in PHASES:
            for item in phases.get(phase, []):
                if isinstance(item, dict):
                    yield project, phase, item


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def append_activity(
    item: dict,
    summary: str,
    *,
    kind: str = "updated",
    actor: str = "agent",
    now: str | None = None,
    details: str | None = None,
) -> dict:
    timestamp = now or utc_stamp()
    event = {
        "timestamp": timestamp,
        "kind": str(kind or "updated"),
        "actor": str(actor or "agent"),
        "summary": str(summary).strip(),
    }
    if details:
        event["details"] = str(details).strip()
    item.setdefault("activity", []).append(event)
    item["updated_at"] = timestamp
    return event


def normalize_item(item: dict, *, now: str | None = None, migration_event: bool = True) -> bool:
    timestamp = now or utc_stamp()
    changed = False
    was_legacy = not item.get("id")
    if was_legacy:
        item["id"] = _new_id()
        changed = True
    if not isinstance(item.get("activity"), list):
        item["activity"] = []
        changed = True
    if not isinstance(item.get("related_items"), list):
        item["related_items"] = []
        changed = True
    else:
        normalized_relations = []
        for relation in item["related_items"]:
            if isinstance(relation, str) and relation.strip():
                normalized_relations.append({"id": relation.strip(), "relation": "related"})
            elif isinstance(relation, dict) and relation.get("id"):
                normalized_relations.append(
                    {
                        "id": str(relation["id"]),
                        "relation": str(relation.get("relation") or "related"),
                    }
                )
        if normalized_relations != item["related_items"]:
            item["related_items"] = normalized_relations
            changed = True
    if not item.get("created_at"):
        item["created_at"] = timestamp
        changed = True
    if not item.get("updated_at"):
        item["updated_at"] = timestamp
        changed = True
    if was_legacy and migration_event:
        append_activity(
            item,
            "Structured history tracking enabled",
            kind="migrated",
            actor="system",
            now=timestamp,
        )
        changed = True
    return changed


def normalize_roadmap(data: dict, *, now: str | None = None, migration_event: bool = True) -> bool:
    changed = False
    seen_ids: set[str] = set()
    for _project, _phase, item in iter_items(data):
        if normalize_item(item, now=now, migration_event=migration_event):
            changed = True
        if item["id"] in seen_ids:
            item["id"] = _new_id()
            append_activity(
                item,
                "Duplicate item identity repaired",
                kind="migrated",
                actor="system",
                now=now,
            )
            changed = True
        seen_ids.add(item["id"])
    return changed


def find_item(data: dict, project: str, name_or_id: str) -> tuple[str, dict]:
    for found_project, phase, item in iter_items(data):
        if found_project == project and (
            item.get("name") == name_or_id or item.get("id") == name_or_id
        ):
            return phase, item
    raise KeyError(f"Roadmap item not found: {project} / {name_or_id}")


def item_index(data: dict) -> dict[str, tuple[str, str, dict]]:
    return {
        item["id"]: (project, phase, item)
        for project, phase, item in iter_items(data)
        if item.get("id")
    }


def _display(value) -> str:
    if value in (None, ""):
        return "∅"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def reconcile_update(
    previous: dict,
    incoming: dict,
    *,
    actor: str = "human-ui",
    now: str | None = None,
) -> bool:
    """Preserve metadata and append one audit event per changed incoming item."""
    timestamp = now or utc_stamp()
    normalize_roadmap(previous, now=timestamp)
    previous_by_id = item_index(previous)
    previous_by_name = {
        (project, item.get("name")): (phase, item)
        for project, phase, item in iter_items(previous)
    }
    changed = False

    for project, phase, item in iter_items(incoming):
        old_phase = None
        old = None
        if item.get("id") in previous_by_id:
            _old_project, old_phase, old = previous_by_id[item["id"]]
        elif (project, item.get("name")) in previous_by_name:
            old_phase, old = previous_by_name[(project, item.get("name"))]

        if old is None:
            normalize_item(item, now=timestamp, migration_event=False)
            append_activity(item, "Item created", kind="created", actor=actor, now=timestamp)
            changed = True
            continue

        item["id"] = old["id"]
        item["activity"] = list(old.get("activity", []))
        item["created_at"] = old.get("created_at", timestamp)
        if "related_items" not in item:
            item["related_items"] = list(old.get("related_items", []))
        item["updated_at"] = old.get("updated_at", timestamp)
        normalize_item(item, now=timestamp, migration_event=False)

        differences = []
        if old_phase != phase:
            differences.append(f"phase: {old_phase} → {phase}")
        fields = sorted((set(old) | set(item)) - IGNORED_DIFF_FIELDS)
        for field in fields:
            if old.get(field) != item.get(field):
                differences.append(
                    f"{field}: {_display(old.get(field))} → {_display(item.get(field))}"
                )
        if differences:
            append_activity(
                item,
                "; ".join(differences),
                kind="updated",
                actor=actor,
                now=timestamp,
            )
            changed = True
    return changed


def _upsert_relation(item: dict, target_id: str, relation: str) -> bool:
    relations = item.setdefault("related_items", [])
    for existing in relations:
        if existing.get("id") == target_id:
            if existing.get("relation") == relation:
                return False
            existing["relation"] = relation
            return True
    relations.append({"id": target_id, "relation": relation})
    return True


def relate_items(
    data: dict,
    project: str,
    item_name: str,
    related_project: str,
    related_name: str,
    *,
    relation: str = "related",
    actor: str = "agent",
    now: str | None = None,
) -> None:
    timestamp = now or utc_stamp()
    normalize_roadmap(data, now=timestamp)
    _phase, item = find_item(data, project, item_name)
    _related_phase, related = find_item(data, related_project, related_name)
    if item["id"] == related["id"]:
        raise ValueError("An item cannot relate to itself")
    relation = (relation or "related").strip().lower()
    inverse = INVERSE_RELATIONS.get(relation, "related")
    if _upsert_relation(item, related["id"], relation):
        append_activity(
            item,
            f"Related to {related_project}::{related.get('name')} ({relation})",
            kind="related",
            actor=actor,
            now=timestamp,
        )
    if _upsert_relation(related, item["id"], inverse):
        append_activity(
            related,
            f"Related to {project}::{item.get('name')} ({inverse})",
            kind="related",
            actor=actor,
            now=timestamp,
        )
