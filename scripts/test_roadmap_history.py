import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def roadmap_with(item, phase="Backlog"):
    phases = {name: [] for name in ("In Progress", "Upcoming", "Backlog", "Done")}
    phases[phase].append(item)
    return {"example-app": phases}


def test_normalize_adds_stable_id_and_migration_activity():
    history = load_module("roadmap_history")
    data = roadmap_with({"name": "Old item"})

    assert history.normalize_roadmap(data, now="2026-07-22T16:00:00Z") is True
    item = data["example-app"]["Backlog"][0]
    assert len(item["id"]) == 12
    assert item["created_at"] == "2026-07-22T16:00:00Z"
    assert item["related_items"] == []
    assert item["activity"][0]["kind"] == "migrated"
    item_id = item["id"]
    assert history.normalize_roadmap(data, now="2026-07-22T17:00:00Z") is False
    assert item["id"] == item_id


def test_reconcile_logs_changes_without_losing_history():
    history = load_module("roadmap_history")
    previous = roadmap_with(
        {
            "id": "abc123def456",
            "name": "Build history",
            "priority": 2,
            "activity": [
                {
                    "timestamp": "2026-07-22T15:00:00Z",
                    "kind": "created",
                    "actor": "agent",
                    "summary": "Item created",
                }
            ],
            "related_items": [],
            "created_at": "2026-07-22T15:00:00Z",
            "updated_at": "2026-07-22T15:00:00Z",
        }
    )
    incoming = roadmap_with({"name": "Build history", "priority": 1}, phase="In Progress")

    history.reconcile_update(
        previous, incoming, actor="human-ui", now="2026-07-22T16:05:00Z"
    )
    item = incoming["example-app"]["In Progress"][0]
    assert item["id"] == "abc123def456"
    assert item["activity"][0]["summary"] == "Item created"
    assert "phase: Backlog → In Progress" in item["activity"][-1]["summary"]
    assert "priority: 2 → 1" in item["activity"][-1]["summary"]


def test_relationships_are_bidirectional_and_logged():
    history = load_module("roadmap_history")
    data = roadmap_with(
        {
            "id": "aaaaaaaaaaaa",
            "name": "Parent",
            "activity": [],
            "related_items": [],
            "created_at": "x",
            "updated_at": "x",
        }
    )
    data["example-app"]["Backlog"].append(
        {
            "id": "bbbbbbbbbbbb",
            "name": "Child",
            "activity": [],
            "related_items": [],
            "created_at": "x",
            "updated_at": "x",
        }
    )

    history.relate_items(
        data,
        "example-app",
        "Parent",
        "example-app",
        "Child",
        relation="blocks",
        actor="agent",
        now="2026-07-22T16:10:00Z",
    )
    parent, child = data["example-app"]["Backlog"]
    assert parent["related_items"] == [{"id": "bbbbbbbbbbbb", "relation": "blocks"}]
    assert child["related_items"] == [
        {"id": "aaaaaaaaaaaa", "relation": "blocked by"}
    ]
    assert parent["activity"][-1]["kind"] == "related"
