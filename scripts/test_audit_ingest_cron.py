from datetime import datetime, timedelta

import audit_ingest_cron as ingest
import ops_audit


def _job(job_id: str, when: datetime, status: str = "ok") -> dict:
    return {
        "id": job_id,
        "name": f"Executor {job_id}",
        "last_run_at": when.isoformat(),
        "last_status": status,
    }


def test_both_executors_are_ingested_and_core_audited():
    assert {"d4exec1014", "d4execnight"} <= ingest.INGEST_JOB_IDS
    assert {"d4exec1014", "d4execnight"} <= ops_audit.CORE_JOB_IDS


def test_vulnerability_autofix_is_ingested_and_core_audited():
    assert "b1fb039a276d" in ingest.INGEST_JOB_IDS
    assert "b1fb039a276d" in ops_audit.CORE_JOB_IDS


def test_registry_reconcile_appends_missing_executor_event():
    now = datetime.now().astimezone()
    jobs = {
        "d4exec1014": _job("d4exec1014", now, "error"),
        "d4execnight": _job("d4execnight", now, "ok"),
    }
    state = {"executor_last_runs": {}}
    appended = []

    count = ingest.reconcile_executor_runs(
        jobs, state, [], append_fn=lambda **event: appended.append(event)
    )

    assert count == 2
    assert {event["job_id"] for event in appended} == {
        "d4exec1014",
        "d4execnight",
    }
    assert state["executor_last_runs"]["d4execnight"] == now.isoformat()
    day_event = next(e for e in appended if e["job_id"] == "d4exec1014")
    assert day_event["status"] == "error"


def test_ops_day_report_human_queue_is_ok_not_blocked():
    report = """OPS DAY REPORT — 2026-08-30

Good:
- 182 audit events; silent=156 ok=25 partial=1.

Human queue:
- APPROVAL: merge green tether #267 Discord slash ACK
- ACTION: Docker Desktop Troubleshoot/factory-reset (or accept Podman)

Improvements applied:
- none
"""
    assert ingest.infer_status(report, {"id": "f6ops2100"}) == "ok"
    assert ingest.infer_status(report, None) == "ok"


def test_explicit_action_gate_still_blocked_for_executor():
    gate = "ACTION: Create SA tether-ci\nStep 1: Open console"
    assert ingest.infer_status(gate, {"id": "d4exec1014"}) == "blocked"
    approval = "APPROVAL NEEDED: merge green PR #267"
    assert ingest.infer_status(approval, {"id": "d4exec1014"}) == "blocked"


def test_skill_mention_of_response_is_not_a_heading():
    dump = """# Cron Job: Roadmap executor (FAILED)

## Prompt
4. **Hybrid gate audit:** Ingest only covers `## Response` agent outputs — a script-only skip leaves a scorecard hole.
AUDIT: --status ok|error|partial|blocked|silent
## Error
```
RuntimeError: Request timed out.
```
"""
    assert ingest.has_response_heading(dump) is False
    assert ingest.extract_response(dump) == ""


def test_real_response_heading_still_ingests():
    text = "# Cron Job\n\n## Response\n\n[SILENT]\n"
    assert ingest.has_response_heading(text) is True
    assert ingest.extract_response(text) == "[SILENT]"


def test_registry_reconcile_does_not_duplicate_covered_run():
    now = datetime.now().astimezone()
    previous = now - timedelta(hours=1)
    jobs = {"d4execnight": _job("d4execnight", now)}
    state = {"executor_last_runs": {"d4execnight": previous.isoformat()}}
    events = [
        {
            "job_id": "d4execnight",
            "ts": (now - timedelta(minutes=1)).isoformat(),
            "status": "silent",
        }
    ]
    appended = []

    count = ingest.reconcile_executor_runs(
        jobs, state, events, append_fn=lambda **event: appended.append(event)
    )

    assert count == 0
    assert appended == []
    assert state["executor_last_runs"]["d4execnight"] == now.isoformat()
