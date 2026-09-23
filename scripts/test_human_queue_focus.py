import json
from pathlib import Path

import pytest

from human_queue_focus import build_focus


def item(item_id, name, *, project="tether", phase="In Progress", priority=2,
         owner="human", blocked=True, reason="ACTION: do it", related=None,
         actions=None):
    return {
        "id": item_id,
        "name": name,
        "project": project,
        "phase": phase,
        "priority": priority,
        "owner": owner,
        "blocked": blocked,
        "blocked_reason": reason,
        "human_actions": actions or ["Do the root action"],
        "related_items": related or [],
        "notes": "",
    }


def test_groups_by_product_and_collapses_dependency_chain():
    root = item("root", "Store Zoom secrets", priority=1)
    child = item(
        "child", "Run Zoom smoke", owner="agent",
        related=[{"id": "root", "relation": "depends on"}],
    )
    focus = build_focus([root, child])
    assert [row["id"] for row in focus["do_next"]] == ["root"]
    assert focus["do_next"][0]["unblocks_count"] == 1
    assert focus["do_next"][0]["dependents"][0]["id"] == "child"
    assert focus["by_product"]["tether"]["do_next_count"] == 1
    assert [row["id"] for row in focus["waiting_agent"]] == ["child"]


def test_holds_and_no_action_backlog_are_later():
    hold = item(
        "hold", "Freeze price", phase="Backlog", priority=1,
        reason="HOLD: no action until product is complete",
        actions=["No action now"],
    )
    focus = build_focus([hold])
    assert not focus["do_next"]
    assert [row["id"] for row in focus["later"]] == ["hold"]


def test_wait_for_agent_action_steps_are_not_later():
    """Human residual SM paste often says 'Wait for agent…' — that is not HOLD."""
    sm = item(
        "zoom-sm",
        "Zoom OAuth SM paste",
        priority=2,
        reason="ACTION: Zoom signed-in verified. Agent owns app create. Residual: paste ZOOM_CLIENT_ID",
        actions=[
            "Wait for agent to complete Zoom Marketplace app create",
            "Paste ZOOM_CLIENT_ID into tether-dev SM",
            "Release",
        ],
    )
    platform = item(
        "platform",
        "Platform accounts",
        priority=1,
        reason="ACTION: DONE: Zoom. REMAINS: Unlock Telegram session",
        actions=[
            "Log in to Telegram",
            "Wait for agent to finish app creates",
            "Paste ZOOM_* and TELEGRAM_* secrets into SM",
            "Release",
        ],
    )
    focus = build_focus([sm, platform])
    assert {row["id"] for row in focus["do_next"]} == {"zoom-sm", "platform"}
    assert not focus["later"]


def test_parent_of_and_child_of_collapse_agent_downstream():
    parent = item("parent", "Platform credentials root", priority=1)
    child = item(
        "child",
        "Live bridge smoke",
        owner="agent",
        related=[{"id": "parent", "relation": "child of"}],
    )
    # Reciprocal link as roadmap_cli relate writes
    parent["related_items"] = [{"id": "child", "relation": "parent of"}]
    focus = build_focus([parent, child])
    assert [row["id"] for row in focus["do_next"]] == ["parent"]
    assert focus["do_next"][0]["unblocks_count"] == 1
    assert [row["id"] for row in focus["waiting_agent"]] == ["child"]


def test_dependency_of_means_target_depends_on_this_root():
    approval = item(
        "apr",
        "APPROVAL merge PR",
        priority=1,
        reason="APPROVAL: merge green PR #227",
        related=[{"id": "cert", "relation": "dependency of"}],
    )
    cert = item(
        "cert",
        "Gchat CASA certification",
        owner="agent",
        related=[{"id": "apr", "relation": "depends on"}],
    )
    focus = build_focus([approval, cert])
    assert [row["id"] for row in focus["do_next"]] == ["apr"]
    assert focus["do_next"][0]["unblocks_count"] == 1
    assert [row["id"] for row in focus["waiting_agent"]] == ["cert"]


def test_missing_related_target_does_not_crash():
    orphan = item(
        "orphan",
        "Broken link",
        related=[{"id": "missing-id", "relation": "depends on"}],
    )
    focus = build_focus([orphan])
    assert [row["id"] for row in focus["do_next"]] == ["orphan"]


def test_rank_uses_priority_phase_fanout_then_stable_identity():
    p2 = item("p2", "P2 root", priority=2)
    p1b = item("p1b", "P1 B", priority=1)
    p1a = item("p1a", "P1 A", priority=1)
    dep = item(
        "dep", "Dependent", owner="agent",
        related=[{"id": "p1b", "relation": "depends on"}],
    )
    focus = build_focus([p2, p1b, p1a, dep])
    assert [row["id"] for row in focus["do_next"]] == ["p1b", "p1a", "p2"]


def test_cross_product_dependency_counts_but_stays_under_root_product():
    root = item("root", "Shared approval", project="hermes-ops", priority=1)
    child = item(
        "child", "Tether deploy", project="tether", owner="agent",
        related=[{"id": "root", "relation": "depends on"}],
    )
    focus = build_focus([root, child])
    assert focus["do_next"][0]["unblocks_count"] == 1
    assert focus["do_next"][0]["dependents"][0]["project"] == "tether"


def test_cycle_does_not_crash_or_hide_both_roots():
    a = item("a", "A", related=[{"id": "b", "relation": "depends on"}])
    b = item("b", "B", related=[{"id": "a", "relation": "depends on"}])
    focus = build_focus([a, b])
    assert {row["id"] for row in focus["do_next"]} == {"a", "b"}
    assert focus["warnings"]


def test_duplicate_gate_signature_collapses_agent_downstream_without_links():
    root = item(
        "zoom-human", "Zoom credentials", priority=1,
        reason="ACTION: paste ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET into SM",
    )
    child = item(
        "zoom-smoke", "Zoom signed smoke", priority=1, owner="agent",
        reason="ACTION: requires ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET in SM",
    )
    combined = item(
        "bridge", "Live bridge", priority=1, owner="agent",
        reason="ACTION: requires ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET, and TELEGRAM_BOT_TOKEN in SM",
    )
    focus = build_focus([root, child, combined])
    assert [row["id"] for row in focus["do_next"]] == ["zoom-human"]
    assert focus["do_next"][0]["unblocks_count"] == 2


def test_only_top_five_are_focus_but_all_roots_remain_discoverable():
    rows = [item(str(i), f"Item {i}", project=f"p{i}", priority=1) for i in range(7)]
    focus = build_focus(rows, limit=5)
    assert len(focus["do_next"]) == 5
    assert len(focus["all_roots"]) == 7
