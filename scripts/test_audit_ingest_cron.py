from datetime import datetime, timedelta

import audit_ingest_cron as ingest


def _job(when: datetime, status: str = "ok") -> dict:
    return {
        "id": "d4exec1014",
        "name": "Roadmap executor",
        "last_run_at": when.isoformat(),
        "last_status": status,
    }


def test_registry_reconcile_appends_missing_executor_event():
    now = datetime.now().astimezone()
    state = {"executor_last_runs": {}}
    appended = []

    count = ingest.reconcile_executor_runs(
        {"d4exec1014": _job(now, "error")},
        state,
        [],
        append_fn=lambda **event: appended.append(event),
    )

    assert count == 1
    assert appended[0]["status"] == "error"
    assert appended[0]["summary"].startswith("[registry-reconcile]")
    assert state["executor_last_runs"]["d4exec1014"] == now.isoformat()


def test_registry_reconcile_does_not_duplicate_covered_run():
    now = datetime.now().astimezone()
    previous = now - timedelta(hours=1)
    state = {"executor_last_runs": {"d4exec1014": previous.isoformat()}}
    events = [
        {
            "job_id": "d4exec1014",
            "ts": (now - timedelta(minutes=1)).isoformat(),
            "status": "silent",
        }
    ]
    appended = []

    count = ingest.reconcile_executor_runs(
        {"d4exec1014": _job(now)},
        state,
        events,
        append_fn=lambda **event: appended.append(event),
    )

    assert count == 0
    assert appended == []
    assert state["executor_last_runs"]["d4exec1014"] == now.isoformat()
