"""Unit tests for paxdev Cursor editor+agent UI smoke."""
from __future__ import annotations

import json
from pathlib import Path

import paxdev_cursor_ui_smoke as smoke


def _fixture(tmp_path: Path, *, loud: int = 1, quiet: int = 0, breaking: int = 2) -> Path:
    pax = tmp_path / ".paxdev"
    pax.mkdir()
    report = {
        "loud_conflicts": [{"file": "app.py", "range_a": [1, 2]}] * loud,
        "quiet_conflicts": [{"file": "calc.py"}] * quiet,
        "breaking_changes": [{"file": "api.py", "use_file": "app.py"}] * breaking,
    }
    (pax / "conflicts.json").write_text(json.dumps(report), encoding="utf-8")
    vscode = tmp_path / ".vscode"
    vscode.mkdir()
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "run_diff_report.py").write_text("# stub\n", encoding="utf-8")
    (vscode / "settings.json").write_text(
        json.dumps(
            {
                "paxdev.apiUrl": "http://127.0.0.1:8000",
                "paxdev.runnerPath": str(runner).replace("\\", "/"),
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_status_bar_zero():
    assert smoke.status_bar_text_from_counts(0, 0, 0) == "$(check) Paxdev: 0 conflicts"


def test_status_bar_counts():
    assert (
        smoke.status_bar_text_from_counts(1, 0, 3)
        == "$(warning) Paxdev: 1 loud, 0 quiet, 3 breaking"
    )


def test_smoke_writes_agent_artifacts(tmp_path: Path):
    ws = _fixture(tmp_path)
    result = smoke.run_smoke(
        workspace=ws,
        require_cursor=False,
        write_artifacts=True,
    )
    assert result["ok"] is True, result
    assert result["counts"] == {"loud": 1, "quiet": 0, "breaking": 2}
    mdc = (ws / ".cursor" / "rules" / "paxdev.mdc").read_text(encoding="utf-8")
    assert "alwaysApply: true" in mdc
    assert "conflicts.json" in mdc
    ctx = (ws / ".paxdev" / "agent_context.md").read_text(encoding="utf-8")
    assert "**Loud**" in ctx and "app.py" in ctx
    assert "breaking" in (ws / "AGENTS.md").read_text(encoding="utf-8").lower()


def test_smoke_fails_without_conflicts(tmp_path: Path):
    result = smoke.run_smoke(workspace=tmp_path, require_cursor=False, write_artifacts=False)
    assert result["ok"] is False
    assert any("conflicts.json" in f for f in result["fails"])


def test_smoke_fails_without_extension_when_cli_ok(tmp_path: Path, monkeypatch):
    ws = _fixture(tmp_path)
    monkeypatch.setattr(
        smoke,
        "list_cursor_extensions",
        lambda _cli: (True, "ok", ["someone.else"]),
    )
    cli = tmp_path / "cursor.cmd"
    cli.write_text("", encoding="utf-8")
    result = smoke.run_smoke(
        workspace=ws,
        cursor_cli=cli,
        require_cursor=True,
        require_extension=True,
        write_artifacts=True,
    )
    assert result["ok"] is False
    assert any("paladin-io.paxdev" in f for f in result["fails"])
