#!/usr/bin/env python3
"""Rank and cluster roadmap Needs-you items without mutating the roadmap."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

PHASE_RANK = {"In Progress": 0, "Upcoming": 1, "Backlog": 2}
KIND_RANK = {"APPROVAL": 0, "ACTION": 1, "HUMAN": 2, "BLOCKED": 3}
# Item A "depends on" B → A waits on B. Reciprocal roadmap_cli forms:
# - child of / blocked by / requires → same as depends on
# - parent of / dependency of → reverse edge (this item is the upstream root)
UPSTREAM_RELATIONS = {"depends on", "blocked by", "requires", "child of"}
DOWNSTREAM_RELATIONS = {"parent of", "dependency of", "blocks"}
ENV_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
WILDCARD_ENV_RE = re.compile(r"\b([A-Z][A-Z0-9]+)_\*")


def kind_of(row: dict) -> str:
    reason = str(row.get("blocked_reason") or "").strip().upper()
    if reason.startswith("APPROVAL:"):
        return "APPROVAL"
    if reason.startswith("ACTION:"):
        return "ACTION"
    if row.get("blocked"):
        return "BLOCKED"
    return "HUMAN"


def _is_later(row: dict) -> bool:
    """True only for explicit deferrals — not 'Wait for agent…' residual steps."""
    reason = str(row.get("blocked_reason") or "").strip()
    upper = reason.upper()
    if upper.startswith("HOLD:") or upper.startswith("WEEKEND-DEFER:"):
        return True
    # Explicit no-action prose in the reason (not human_actions "wait for agent").
    if "NO ACTION" in upper and (
        upper.startswith("HOLD") or "HOLD:" in upper or row.get("phase") == "Backlog"
    ):
        return True
    if "AFTER PRICE FREEZE" in upper:
        return True
    return row.get("phase") == "Backlog" and int(row.get("priority") or 3) >= 3


def _domain_tokens(row: dict) -> set[str]:
    text = " ".join(
        [str(row.get("name") or ""), str(row.get("blocked_reason") or "")]
    ).lower()
    return set(re.findall(r"zoom|telegram|stripe|gchat|scheduler|billing|casa", text))


def _signature(row: dict) -> tuple[str, ...]:
    text = " ".join(
        [
            str(row.get("name") or ""),
            str(row.get("blocked_reason") or ""),
            " ".join(str(x) for x in (row.get("human_actions") or [])),
        ]
    )
    upper = text.upper()
    env = set(ENV_TOKEN_RE.findall(upper))
    # Treat ZOOM_* / TELEGRAM_* wildcards as domain family tokens for collapse.
    for prefix in WILDCARD_ENV_RE.findall(upper):
        env.add(f"{prefix}_*")
    if env:
        return tuple(sorted(env))
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    domain = sorted(words & {"zoom", "telegram", "stripe", "gchat", "scheduler", "billing", "casa"})
    gate = sorted(words & {"secret", "secrets", "credential", "credentials", "approval", "login", "sm"})
    return tuple(domain + gate) if domain and gate else ()


def _rank(row: dict) -> tuple:
    emergency = bool(re.search(r"security|data[- ]?loss|incident", str(row.get("blocked_reason") or ""), re.I))
    return (
        0 if emergency else 1,
        int(row.get("priority") or 3),
        PHASE_RANK.get(str(row.get("phase") or ""), 9),
        -int(row.get("unblocks_count") or 0),
        KIND_RANK.get(kind_of(row), 9),
        str(row.get("project") or ""),
        str(row.get("id") or row.get("name") or ""),
    )


def _brief(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "project": row.get("project"),
        "name": row.get("name"),
        "phase": row.get("phase"),
        "priority": row.get("priority"),
        "owner": row.get("owner"),
        "kind": kind_of(row),
    }


def build_focus(rows: Iterable[dict], *, limit: int = 5) -> dict:
    items = [dict(row) for row in rows if isinstance(row, dict) and row.get("phase") != "Done"]
    by_id = {str(row.get("id")): row for row in items if row.get("id")}
    downstream: dict[str, set[str]] = defaultdict(set)
    upstream: dict[str, set[str]] = defaultdict(set)

    for row in items:
        rid = str(row.get("id") or "")
        if not rid:
            continue
        for link in row.get("related_items") or []:
            if not isinstance(link, dict):
                continue
            target = str(link.get("id") or "")
            relation = str(link.get("relation") or "").strip().lower()
            if target not in by_id:
                continue
            if relation in UPSTREAM_RELATIONS:
                # rid depends on target → target is upstream root
                upstream[rid].add(target)
                downstream[target].add(rid)
            elif relation in DOWNSTREAM_RELATIONS:
                # target depends on rid → rid is upstream root
                upstream[target].add(rid)
                downstream[rid].add(target)

    # Infer duplicate downstream gates only from strong shared secret/env identifiers.
    sig_groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for row in items:
        sig = _signature(row)
        if sig:
            sig_groups[sig].append(row)
    for group in sig_groups.values():
        humans = [r for r in group if str(r.get("owner") or "agent").lower() == "human"]
        if not humans:
            continue
        root = min(humans, key=_rank)
        root_id = str(root.get("id") or "")
        root_sig = set(_signature(root))
        root_domains = _domain_tokens(root)
        for row in items:
            rid = str(row.get("id") or "")
            row_sig = set(_signature(row))
            row_domains = _domain_tokens(row)
            if (
                rid
                and rid != root_id
                and str(row.get("owner") or "agent").lower() == "agent"
                and root_sig
                and root_sig.issubset(row_sig)
                and root_domains
                and root_domains.issubset(row_domains)
            ):
                upstream[rid].add(root_id)
                downstream[root_id].add(rid)

    warnings: list[str] = []
    for rid, parents in upstream.items():
        if any(rid in upstream.get(parent, set()) for parent in parents):
            warnings.append(f"dependency cycle involving {rid}")

    actionable = [
        row for row in items
        if row.get("blocked") or str(row.get("owner") or "agent").lower() == "human"
    ]
    later = [row for row in actionable if _is_later(row)]
    later_ids = {str(row.get("id") or "") for row in later}
    waiting_ids = {
        str(row.get("id") or "")
        for row in actionable
        if str(row.get("owner") or "agent").lower() == "agent" and upstream.get(str(row.get("id") or ""))
    }

    roots: list[dict] = []
    for row in actionable:
        rid = str(row.get("id") or "")
        if rid in later_ids or rid in waiting_ids:
            continue
        parents = upstream.get(rid, set())
        # Cycles remain visible instead of hiding every member.
        if parents and not any(rid in upstream.get(parent, set()) for parent in parents):
            continue
        roots.append(row)

    for root in roots:
        rid = str(root.get("id") or "")
        seen: set[str] = set()
        stack = list(downstream.get(rid, set()))
        while stack:
            child = stack.pop()
            if child in seen or child == rid:
                continue
            seen.add(child)
            stack.extend(downstream.get(child, set()))
        root["dependents"] = [_brief(by_id[x]) for x in sorted(seen) if x in by_id]
        root["unblocks_count"] = len(root["dependents"])
        root["kind"] = kind_of(root)

    roots.sort(key=_rank)
    later.sort(key=_rank)
    waiting = [row for row in actionable if str(row.get("id") or "") in waiting_ids]
    waiting.sort(key=_rank)

    products: dict[str, dict] = {}
    for product in sorted({str(row.get("project") or "unknown") for row in actionable}):
        products[product] = {
            "do_next_count": sum(1 for row in roots if row.get("project") == product),
            "later_count": sum(1 for row in later if row.get("project") == product),
            "waiting_count": sum(1 for row in waiting if row.get("project") == product),
        }

    return {
        "do_next": roots[: max(0, limit)],
        "all_roots": roots,
        "later": later,
        "waiting_agent": waiting,
        "by_product": products,
        "total_open": len(actionable),
        "warnings": sorted(set(warnings)),
    }
