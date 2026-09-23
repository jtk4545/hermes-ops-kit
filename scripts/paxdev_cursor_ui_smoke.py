#!/usr/bin/env python3
"""Paxdev Cursor editor+agent UI smoke (human using an editor with an agent).

Landing HTTP is not the product. This checks the loop a developer+agent actually uses:
  1) Cursor has the Paxdev extension
  2) Fixture workspace has loud/quiet/breaking reports
  3) Status-bar copy matches extension formula
  4) Agent-facing artifacts exist (.cursor/rules/paxdev.mdc, .paxdev/agent_context.md)

Does not drive the Cursor GUI (cua-driver is a separate lane). Cheap enough for every
ui-live-scan tick. Skip (not fail) when Cursor CLI is missing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_FIXTURE = Path(os.environ.get("PAXDEV_CURSOR_FIXTURE", str(Path.home() / "simple_calc")))
_local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
DEFAULT_CURSOR = Path(
    os.environ.get(
        "PAXDEV_CURSOR_CLI",
        str(Path(_local) / "Programs" / "cursor" / "resources" / "app" / "bin" / "cursor.cmd"),
    )
)
EXTENSION_ID = "paladin-io.paxdev"
AGENT_MARKERS = ("loud", "quiet", "breaking", "conflicts.json")


def status_bar_text_from_counts(loud: int, quiet: int, breaking: int) -> str:
    """Must stay in lockstep with extension/src/statusBarText.ts."""
    loud = max(0, int(loud))
    quiet = max(0, int(quiet))
    breaking = max(0, int(breaking))
    if loud == 0 and quiet == 0 and breaking == 0:
        return "$(check) Paxdev: 0 conflicts"
    return f"$(warning) Paxdev: {loud} loud, {quiet} quiet, {breaking} breaking"


def parse_conflict_counts(report: dict) -> dict[str, int]:
    return {
        "loud": len(report.get("loud_conflicts") or []),
        "quiet": len(report.get("quiet_conflicts") or []),
        "breaking": len(report.get("breaking_changes") or []),
    }


def _first_conflict_file(report: dict) -> str:
    for key in ("loud_conflicts", "quiet_conflicts", "breaking_changes"):
        rows = report.get(key) or []
        if rows and isinstance(rows[0], dict):
            f = str(rows[0].get("file") or rows[0].get("use_file") or "").strip()
            if f:
                return f
    return ""


def build_agent_context_md(workspace: Path, report: dict) -> str:
    counts = parse_conflict_counts(report)
    sample = _first_conflict_file(report)
    pax = workspace / ".paxdev"
    lines = [
        "# Paxdev conflict context for agent",
        "",
        "Resolve conflicts between the current branch and **main** (git **merge-base**).",
        "",
        "## Summary",
        "",
        "| Type | Count | Meaning |",
        "|------|-------|---------|",
        f"| **Loud** | {counts['loud']} | Same file, overlapping line changes |",
        f"| **Quiet** | {counts['quiet']} | Connected control/data flow, no line overlap |",
        f"| **Breaking** | {counts['breaking']} | One side changed an API the other still uses |",
        "",
        "Start at `.paxdev/conflicts.json`. For quiet/breaking also read "
        "`.paxdev/partial_graph.json` / `.paxdev/ast_graph.json`.",
        "",
        f"- Conflicts report: `{pax / 'conflicts.json'}`",
        f"- Partial graph: `{pax / 'partial_graph.json'}`",
        f"- Agent context: `{pax / 'agent_context.md'}`",
    ]
    if sample:
        lines.extend(["", f"Example conflict file: `{sample}`"])
    lines.append("")
    return "\n".join(lines)


def build_cursor_rule_mdc() -> str:
    return """---
description: Paxdev — monitor .paxdev reports for merge conflicts and breaking changes
alwaysApply: true
---

# Paxdev

This project uses **Paxdev**. After edits, read `.paxdev/conflicts.json` (loud / quiet / breaking)
and `.paxdev/agent_context.md` before claiming work is done or ready to merge.

Quiet and breaking need `.paxdev/partial_graph.json` / `.paxdev/ast_graph.json` — do not skip graphs.
Use **Paxdev: Send conflict context to agent** if the report is missing from chat.
"""


def ensure_agent_artifacts(workspace: Path, report: dict) -> dict[str, str]:
    """Write missing agent-facing files so a human+agent loop is actually present."""
    out: dict[str, str] = {}
    pax = workspace / ".paxdev"
    pax.mkdir(parents=True, exist_ok=True)
    ctx = pax / "agent_context.md"
    ctx.write_text(build_agent_context_md(workspace, report), encoding="utf-8")
    out["agent_context"] = str(ctx)
    rules = workspace / ".cursor" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    mdc = rules / "paxdev.mdc"
    mdc.write_text(build_cursor_rule_mdc(), encoding="utf-8")
    out["cursor_rule"] = str(mdc)
    agents = workspace / "AGENTS.md"
    if not agents.is_file() or "paxdev-agent-hints" not in agents.read_text(encoding="utf-8", errors="replace"):
        block = (
            "# AGENTS\n\n"
            "<!-- paxdev-agent-hints begin -->\n"
            "## Paxdev — conflict & breaking-change reports\n\n"
            "Read `.paxdev/conflicts.json` and `.paxdev/agent_context.md` "
            "(loud / quiet / breaking) before merging.\n"
            "<!-- paxdev-agent-hints end -->\n"
        )
        agents.write_text(block, encoding="utf-8")
    out["agents_md"] = str(agents)
    return out


def list_cursor_extensions(cursor_cli: Path) -> tuple[bool, str, list[str]]:
    """Return (ok, detail, extension_ids). ok=False means CLI missing (skip)."""
    if not cursor_cli.is_file():
        return False, f"skip: cursor CLI missing ({cursor_cli})", []
    try:
        r = subprocess.run(
            [str(cursor_cli), "--list-extensions"],
            capture_output=True,
            text=True,
            timeout=45,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"skip: cursor --list-extensions failed ({exc})", []
    ids = [ln.strip().lower() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if r.returncode != 0 and not ids:
        return False, f"skip: cursor --list-extensions code={r.returncode}", []
    return True, "ok", ids


def check_workspace_settings(workspace: Path) -> list[str]:
    settings = workspace / ".vscode" / "settings.json"
    fails: list[str] = []
    if not settings.is_file():
        return [f"missing {settings}"]
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"settings.json invalid: {exc}"]
    if not str(data.get("paxdev.apiUrl") or "").strip():
        fails.append("paxdev.apiUrl unset")
    runner = Path(str(data.get("paxdev.runnerPath") or ""))
    if runner.as_posix() and not (runner / "run_diff_report.py").is_file():
        fails.append(f"paxdev.runnerPath missing run_diff_report.py ({runner})")
    return fails


def check_agent_readable(workspace: Path, report: dict) -> list[str]:
    fails: list[str] = []
    mdc = workspace / ".cursor" / "rules" / "paxdev.mdc"
    ctx = workspace / ".paxdev" / "agent_context.md"
    agents = workspace / "AGENTS.md"
    for path in (mdc, ctx):
        if not path.is_file():
            fails.append(f"missing {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        missing = [m for m in AGENT_MARKERS if m not in text]
        if missing:
            fails.append(f"{path.name} missing markers {missing}")
    if mdc.is_file():
        raw = mdc.read_text(encoding="utf-8", errors="replace")
        if "alwaysApply: true" not in raw:
            fails.append("paxdev.mdc missing alwaysApply: true")
    if agents.is_file():
        text = agents.read_text(encoding="utf-8", errors="replace").lower()
        if "conflicts.json" not in text:
            fails.append("AGENTS.md missing conflicts.json")
    sample = _first_conflict_file(report)
    if sample and ctx.is_file():
        if sample.lower() not in ctx.read_text(encoding="utf-8", errors="replace").lower():
            fails.append(f"agent_context.md missing conflict file {sample}")
    return fails


def run_smoke(
    *,
    workspace: Path | None = None,
    cursor_cli: Path | None = None,
    write_artifacts: bool = True,
    require_extension: bool = True,
    require_cursor: bool = True,
) -> dict:
    workspace = Path(workspace or DEFAULT_FIXTURE)
    cursor_cli = Path(cursor_cli or DEFAULT_CURSOR)
    checks: list[dict] = []
    skips: list[str] = []
    fails: list[str] = []

    def rec(name: str, ok: bool, detail: str, skip: bool = False) -> None:
        checks.append({"name": name, "ok": ok, "skip": skip, "detail": detail})
        if skip:
            skips.append(f"{name}: {detail}")
        elif not ok:
            fails.append(f"{name}: {detail}")

    report_path = workspace / ".paxdev" / "conflicts.json"
    if not report_path.is_file():
        rec("conflicts.json", False, f"missing {report_path}")
        return _result(False, checks, skips, fails, workspace)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        rec("conflicts.json", False, f"invalid JSON: {exc}")
        return _result(False, checks, skips, fails, workspace)

    counts = parse_conflict_counts(report)
    rec(
        "conflict-counts",
        counts["loud"] + counts["quiet"] + counts["breaking"] > 0,
        f"loud={counts['loud']} quiet={counts['quiet']} breaking={counts['breaking']}",
    )
    bar = status_bar_text_from_counts(**counts)
    rec("status-bar-copy", "Paxdev:" in bar, bar)

    if write_artifacts:
        ensure_agent_artifacts(workspace, report)
        rec("agent-artifacts-written", True, "agent_context.md + paxdev.mdc + AGENTS.md")

    for msg in check_agent_readable(workspace, report):
        rec("agent-readable", False, msg)
    if not any(c["name"] == "agent-readable" and not c["ok"] for c in checks):
        rec("agent-readable", True, "mdc + agent_context + AGENTS.md")

    for msg in check_workspace_settings(workspace):
        rec("workspace-settings", False, msg)
    if not any(c["name"] == "workspace-settings" and not c["ok"] for c in checks):
        rec("workspace-settings", True, str(workspace / ".vscode" / "settings.json"))

    if require_cursor:
        ok_cli, detail, ids = list_cursor_extensions(cursor_cli)
        if not ok_cli:
            rec("cursor-cli", True, detail, skip=True)
        else:
            rec("cursor-cli", True, str(cursor_cli))
            present = any(EXTENSION_ID in i for i in ids)
            if require_extension and not present:
                rec("cursor-extension", False, f"{EXTENSION_ID} not installed")
            else:
                rec("cursor-extension", True, EXTENSION_ID if present else "not required")
    else:
        rec("cursor-cli", True, "not required", skip=True)

    ok = not fails
    return _result(ok, checks, skips, fails, workspace, counts=counts, status_bar=bar)


def _result(
    ok: bool,
    checks: list[dict],
    skips: list[str],
    fails: list[str],
    workspace: Path,
    counts: dict | None = None,
    status_bar: str = "",
) -> dict:
    return {
        "ok": ok,
        "product": "paxdev",
        "surface": "cursor-editor-agent",
        "workspace": str(workspace),
        "counts": counts or {},
        "status_bar": status_bar,
        "checks": checks,
        "skips": skips,
        "fails": fails,
        "summary": (
            "ok"
            if ok and not skips
            else ("ok with skips: " + "; ".join(skips) if ok else "FAIL " + "; ".join(fails))
        ),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    result = run_smoke()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
