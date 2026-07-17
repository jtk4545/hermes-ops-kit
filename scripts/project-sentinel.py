#!/usr/bin/env python3
"""Project Sentinel — daily local health-check digest for all user projects."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ops_config import projects_root, sentinel_projects  # noqa: E402
BASE = projects_root()
BRAIN_DIR = Path(os.environ.get("HERMES_BRAIN_DIR", os.path.expandvars(r"%LOCALAPPDATA%\hermes\brain")))
SCRIPTS = Path(__file__).resolve().parent

PROJECTS = sentinel_projects()


def run_cmd(cmd, cwd=None, timeout=180):
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        return result.returncode == 0, [ln for ln in out.splitlines() if ln.strip()]
    except subprocess.TimeoutExpired:
        return False, ["TIMEOUT"]
    except FileNotFoundError:
        return False, [f"Command not found: {cmd[0]}"]
    except Exception as exc:
        return False, [str(exc)]


def count_yaml_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for p in path.rglob("*.yaml"))


def count_json_key(path: Path, key: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return len(data.get(key, []))
    except Exception:
        return 0


def write_brain_health(results: list[dict], action_items: list[str]) -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## Local health (sentinel) — {stamp}",
        "",
    ]
    for row in results:
        status = "OK" if row["ok"] else "FAIL"
        lines.append(f"- **{row['project']}**: {status} — {row['summary']}")
    if action_items:
        lines.append("")
        lines.append("### Action items")
        for item in action_items:
            lines.append(f"- {item}")
    lines.append("")
    block = "\n".join(lines)
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    # Replace prior sentinel section or prepend
    marker = "## Local health (sentinel)"
    if marker in existing:
        pre = existing.split(marker)[0].rstrip() + "\n\n"
        # drop old sentinel through next ## or EOF
        rest = existing.split(marker, 1)[1]
        if "\n## " in rest:
            rest = rest.split("\n## ", 1)[1]
            existing = pre + block + "## " + rest
        else:
            existing = pre + block
    else:
        existing = existing.rstrip() + "\n\n" + block
    pipe.write_text(existing, encoding="utf-8")


def main() -> int:
    action_items: list[str] = []
    results: list[dict] = []
    fail_detail: list[str] = []

    for proj_name, proj in PROJECTS.items():
        path: Path = proj["path"]
        if not path.is_dir():
            action_items.append(f"{proj_name}: directory not found")
            results.append({"project": proj_name, "ok": False, "summary": "missing directory"})
            continue

        fails = []
        for desc, cmd in proj["checks"]:
            ok, lines = run_cmd(cmd, cwd=path)
            if not ok:
                fails.append(desc)
                action_items.append(f"{proj_name}: {desc} failed")
                for ln in lines[-3:]:
                    fail_detail.append(f"{proj_name}/{desc}: {ln}")

        results.append(
            {
                "project": proj_name,
                "ok": not fails,
                "summary": "all checks passed" if not fails else "; ".join(fails),
            }
        )

    present = sum(1 for p in PROJECTS.values() if p["path"].is_dir())
    try:
        write_brain_health(results, action_items)
    except Exception as exc:
        print(f"Brain write skipped: {exc}", file=sys.stderr)

    try:
        from ops_audit import append_event

        append_event(
            job_id="41cb7755ae6d",
            name="Project Sentinel",
            status="error" if action_items else "ok",
            summary=(
                f"Health check {present}/{len(PROJECTS)} present; "
                f"{len(action_items)} action item(s)"
            ),
            detail="\n".join(action_items[:12]),
            artifacts=[str(BRAIN_DIR / "PIPELINES.md")],
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)

    if not action_items:
        return 0  # silent — healthy

    # Telegram only when something failed
    print("PROJECT SENTINEL — issues found")
    print(f"Projects present: {present}/{len(PROJECTS)}")
    print(f"\nACTION ITEMS ({len(action_items)}):")
    for item in action_items:
        print(f"  ! {item}")
    for ln in fail_detail[:20]:
        print(f"  {ln}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
