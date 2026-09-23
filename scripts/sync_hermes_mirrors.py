#!/usr/bin/env python3
"""Keep HERMES_HOME and ~/.hermes mirrors in sync (scripts, roadmap UI, design docs)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path(os.environ.get("LOCALAPPDATA", "")) / "hermes"))
DOT_HERMES = Path.home() / ".hermes"

# Relative paths to mirror (newer mtime wins)
MIRROR_PATHS = [
    "scripts/roadmap.html",
    "scripts/ops.css",
    "scripts/ops-shell.js",
    "scripts/focus.html",
    "scripts/focus_board.py",
    "scripts/test_focus_board.py",
    "scripts/tests/e2e/tracers/ops-focus-shell.spec.mjs",
    "scripts/roadmap_history.py",
    "scripts/tests/e2e/tracers/roadmap-history.spec.mjs",
    "scripts/instances.html",
    "scripts/tests/e2e/tracers/instances-dashboard.spec.mjs",
    "scripts/server.py",
    "scripts/instances_registry.py",
    "scripts/instances.json",
    "scripts/roadmap_cli.py",
    "scripts/roadmap_execution_state.py",
    "scripts/gh_ops.py",
    "scripts/pr-monitor.py",
    "scripts/pipeline-scan.py",
    "scripts/ui-live-scan.py",
    "scripts/paxdev_cursor_ui_smoke.py",
    "scripts/test_paxdev_cursor_ui_smoke.py",
    "scripts/gcloud-ops-scan.py",
    "scripts/readonly_gcp_topology_probe.py",
    "scripts/ops_day_digest.py",
    "scripts/audit_ingest_cron.py",
    "scripts/human_queue_watch.py",
    "scripts/night_executor_window.py",
    "scripts/weekend_policy.py",
    "scripts/brain_read.py",
    "scripts/brain_write.py",
    "scripts/brain_consolidate.py",
    "scripts/brain_paths.py",
    "scripts/human_block_format.py",
    "scripts/roadmap_auto_unblock.py",
    "scripts/test_roadmap_auto_unblock.py",
    "scripts/project-sentinel.py",
    "scripts/sync_hermes_mirrors.py",
    "scripts/roadmap_ui_watchdog.py",
    "scripts/ops_audit.py",
    "scripts/audit.html",
    "scripts/release_manager.py",
    "scripts/release_change_risk.py",
    "scripts/release_preflight.py",
    "scripts/release_deploy_watch.py",
    "scripts/release_post_deploy.py",
    "scripts/release_manifests.py",
    "scripts/releases.html",
    "scripts/test_release_manager.py",
    "scripts/jobs.html",
    "scripts/jobs_schedule.py",
    "scripts/sync_quality_skill.py",
    "scripts/update_pm_decision_policy.py",
    "scripts/market_evidence_validate.py",
    "scripts/test_market_evidence_validate.py",
    "scripts/distribution_validate.py",
    "scripts/test_distribution_validate.py",
    "scripts/pain_to_proof_brief.py",
    "scripts/test_pain_to_proof_brief.py",
    "scripts/market_decision_scorecard.py",
    "scripts/test_market_decision_scorecard.py",
    "scripts/demand_listen.py",
    "scripts/demand_validate.py",
    "scripts/test_demand_validate.py",
    "scripts/revamp_pm_market_demand.py",
    "scripts/on_demand_execution.py",
    "scripts/test_on_demand_execution.py",
    "scripts/executor_run_contract.py",
    "scripts/test_executor_run_contract.py",
    "skills/productivity/roadmap/references/pm-q-bank.md",
    "skills/research/market-research/references/market-q-bank.md",
    "scripts/test_market_pm_qbank_contract.py",
    "scripts/market_pm_qbank_contract.py",
    "PRODUCT_MANAGER_POLICY.md",
    "OPS_DESIGN.md",
    "OPS_MODELS.md",
    "GITHUB_SERVICE_ACCOUNT.md",
    "GCLOUD_OPS_SETUP.md",
]

SKILL_GLOBS = [
    "skills/productivity/brain/SKILL.md",
    "skills/productivity/roadmap/SKILL.md",
    "skills/productivity/ops-daily-review/SKILL.md",
    "skills/productivity/ops-daily-review/references/day-night-model-routing.md",
    "skills/research/market-research/SKILL.md",
    "skills/software-development/dev-test-loop/SKILL.md",
    "skills/software-development/dev-test-loop/references/executor-q-bank.md",
    "skills/software-development/production-assurance/SKILL.md",
    "skills/software-development/release-manager/SKILL.md",
    "skills/software-development/quality-principles/SKILL.md",
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

    # Always leave a CORE_JOB_IDS scorecard event. Empty stdout stays silent
    # for Telegram; a no-op used to skip append_event and punch a daily hole.
    try:
        from ops_audit import append_event

        if changes:
            append_event(
                job_id="g8sync0615",
                name="Sync Hermes mirrors",
                status="ok",
                summary=f"Synced {len(changes)} path(s)",
                detail="\n".join(changes[:20]),
            )
        else:
            append_event(
                job_id="g8sync0615",
                name="Sync Hermes mirrors",
                status="silent",
                summary="No-op; mirrors already in sync",
                detail="",
            )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0  # silent on success — no Telegram for routine syncs


if __name__ == "__main__":
    sys.exit(main())
