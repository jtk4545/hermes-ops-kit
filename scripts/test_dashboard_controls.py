import importlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))


def load_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_jobs_payload_marks_running_and_queued(monkeypatch):
    jobs = load_module("jobs_schedule")
    monkeypatch.setattr(
        jobs,
        "load_jobs_raw",
        lambda: [
            {
                "id": "active",
                "name": "Active",
                "enabled": True,
                "schedule": {"expr": "0 1 * * *"},
            },
            {
                "id": "queued",
                "name": "Queued",
                "enabled": True,
                "schedule": {"expr": "0 1 * * *"},
                "next_run_at": "2000-01-01T00:00:00-06:00",
            },
        ],
    )
    monkeypatch.setattr(jobs, "running_job_ids", lambda: {"active"})

    by_id = {job["id"]: job for job in jobs.jobs_payload()["jobs"]}
    assert by_id["active"]["running"] is True
    assert by_id["active"]["can_run"] is False
    assert by_id["queued"]["queued"] is True
    assert by_id["queued"]["can_run"] is False


def test_trigger_job_once_rejects_running(monkeypatch):
    server = load_module("server")
    monkeypatch.setattr(
        server,
        "_job_status",
        lambda _job_id: {
            "exists": True,
            "enabled": True,
            "running": True,
            "queued": False,
        },
    )
    queue = Mock()
    monkeypatch.setattr(server, "_queue_job_for_next_tick", queue)

    with pytest.raises(server.JobRunConflict, match="already running"):
        server.trigger_job_once("abc123")
    queue.assert_not_called()


def test_trigger_job_once_queues_without_inline_execution(monkeypatch):
    server = load_module("server")
    monkeypatch.setattr(
        server,
        "_job_status",
        lambda _job_id: {
            "exists": True,
            "enabled": True,
            "running": False,
            "queued": False,
        },
    )
    queued = Mock(return_value={"id": "abc123"})
    monkeypatch.setattr(server, "_queue_job_for_next_tick", queued)

    result = server.trigger_job_once("abc123")
    queued.assert_called_once_with("abc123")
    assert result["state"] == "queued"


def test_stale_unfinished_session_is_not_running(tmp_path, monkeypatch):
    jobs = load_module("jobs_schedule")
    database = tmp_path / "state.db"
    now = time.time()
    con = sqlite3.connect(database)
    con.execute("create table sessions (id text, source text, started_at real, ended_at real)")
    con.execute("create table messages (session_id text, timestamp real)")
    con.execute(
        "insert into sessions values (?, 'cron', ?, null)",
        ("cron_active_20260720_172100", now),
    )
    con.execute(
        "insert into messages values (?, ?)",
        ("cron_active_20260720_172100", now),
    )
    con.execute(
        "insert into sessions values (?, 'cron', ?, null)",
        ("cron_stale_20260720_160000", now - 2 * 3600),
    )
    con.execute(
        "insert into messages values (?, ?)",
        ("cron_stale_20260720_160000", now - 2 * 3600),
    )
    con.commit()
    con.close()
    monkeypatch.setattr(jobs, "STATE_DB", database)
    assert jobs._active_session_job_ids() == {"active"}


def test_jobs_ui_contains_run_once_control():
    html = (SCRIPTS / "jobs.html").read_text(encoding="utf-8")
    assert 'data-run-job=' in html
    assert 'fetch("/api/jobs/"' in html
