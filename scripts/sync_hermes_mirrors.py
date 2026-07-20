#!/usr/bin/env python3
"""Keep HERMES_HOME and ~/.hermes mirrors in sync (scripts, roadmap UI, design docs)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

try:
    from hermes_paths import dot_hermes, hermes_home
except Exception:
    def hermes_home():
        env = os.environ.get("HERMES_HOME", "").strip()
        if env:
            return Path(env)
        return Path.home() / ".local" / "share" / "hermes"

    def dot_hermes():
        return Path.home() / ".hermes"

HERMES_HOME = hermes_home()
DOT_HERMES = dot_hermes()

# Relative paths to mirror (newer mtime wins)
MIRROR_PATHS = [
    "scripts/roadmap.html",
    "scripts/server.py",
    "scripts/roadmap_cli.py",
    "scripts/gh_ops.py",
    "scripts/pr-monitor.py",
    "scripts/pipeline-scan.py",
    "scripts/ops_day_digest.py",
    "scripts/audit_ingest_cron.py",
    "scripts/human_queue_watch.py",
    "scripts/weekend_policy.py",
    "scripts/brain_read.py",
    "scripts/brain_write.py",
    "scripts/brain_consolidate.py",
    "scripts/brain_paths.py",
    "scripts/hermes_paths.py",
    "scripts/ops_config.py",
    "scripts/human_block_format.py",
    "scripts/project-sentinel.py",
    "scripts/sync_hermes_mirrors.py",
    "scripts/roadmap_ui_watchdog.py",
    "scripts/ops_audit.py",
    "scripts/audit.html",
    "scripts/jobs.html",
    "scripts/jobs_schedule.py",
    "scripts/sync_quality_skill.py",
    "OPS_DESIGN.md",
    "OPS_MODELS.md",
    "GITHUB_SERVICE_ACCOUNT.md",
]

SKILL_GLOBS = [
    "skills/productivity/brain/SKILL.md",
    "skills/productivity/roadmap/SKILL.md",
    "skills/productivity/ops-daily-review/SKILL.md",
    "skills/software-development/dev-test-loop/SKILL.md",
    "skills/software-development/human-approval/SKILL.md",
    "skills/github/auto-pr-fixer/SKILL.md",
]


def sync_pair(a: Path, b: Path) -> str | None:
    """Copy newer → older. Returns description or None."""
    a_exists, b_exists = a.is_file(), b.is_file()
    if not a_exists and not b_exists:
        return None
    if a_exists and not b_exists:
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, b)
        return f"copied {a} → {b}"
    if b_exists and not a_exists:
        a.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b, a)
        return f"copied {b} → {a}"
    if a.stat().st_mtime > b.stat().st_mtime + 1:
        shutil.copy2(a, b)
        return f"updated {b} from newer {a}"
    if b.stat().st_mtime > a.stat().st_mtime + 1:
        shutil.copy2(b, a)
        return f"updated {a} from newer {b}"
    return None


def main() -> int:
    if not HERMES_HOME.is_dir():
        print(f"HERMES_HOME missing: {HERMES_HOME}", file=sys.stderr)
        return 1
    DOT_HERMES.mkdir(parents=True, exist_ok=True)
    changes: list[str] = []
    for rel in MIRROR_PATHS + SKILL_GLOBS:
        # skills live under HERMES_HOME; also mirror under ~/.hermes when present
        left = HERMES_HOME / rel
        right = DOT_HERMES / rel
        # design docs at both roots
        if rel.startswith("skills/"):
            # optional on ~/.hermes
            pass
        msg = sync_pair(left, right)
        if msg:
            changes.append(msg)

    if not changes:
        return 0  # silent
    try:
        from ops_audit import append_event

        append_event(
            job_id="g8sync0615",
            name="Sync Hermes mirrors",
            status="ok",
            summary=f"Synced {len(changes)} path(s)",
            detail="\n".join(changes[:20]),
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0  # silent on success — no Telegram for routine syncs


if __name__ == "__main__":
    sys.exit(main())
