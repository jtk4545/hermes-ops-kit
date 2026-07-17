#!/usr/bin/env python3
"""Scan main/dev/qa CI for wired repos; write brain/PIPELINES.md; wakeAgent gate.

Important: high-frequency workflows (Status Page) can push real failures out of
`gh run list --limit N`. We therefore (1) skip noise workflows, (2) require
include-pattern match for autofix wake, and (3) explicitly poll critical
workflows per repo (from ops-config critical_workflows).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR  # noqa: E402
from brain_write import _atomic_write, replace_section  # noqa: E402

try:
    from ops_config import repo_name_map, critical_workflows, load_config

    REPOS = repo_name_map()
    CRITICAL_WORKFLOWS = critical_workflows()
    TRACKED_BRANCHES = set(
        load_config().get("tracked_branches") or ["main", "trunk", "dev", "qa"]
    )
except Exception:
    REPOS = {}
    CRITICAL_WORKFLOWS = {}
    TRACKED_BRANCHES = {"main", "trunk", "dev", "qa"}

# Never wake / never treat as autofix targets
SKIP_WF = (
    "release",
    "prod",
    "production",
    "hotfix",
    "status page",
    "status-page",
    "dependabot",
    "dependency graph",
)

# Must match at least one (lowercase substring) to count as actionable
INCLUDE_WF = (
    "pr validation",
    "deploy to dev",
    "dev deploy",
    "gcp dev",
    "deploy",
    "ci",
    "qa integration",
    "qa",
    "lint",
    "test",
    "e2e",
    "nightly",
)


def gh_json(args: list[str]):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=90)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def wf_name(run: dict) -> str:
    return (run.get("workflowName") or run.get("name") or "").strip()


def should_skip_wf(name: str) -> bool:
    low = (name or "").lower()
    return any(p in low for p in SKIP_WF)


def should_include_wf(name: str) -> bool:
    low = (name or "").lower()
    if should_skip_wf(name):
        return False
    # Prefer longer/more specific matches: "deploy to dev" before bare "pr"
    # Avoid matching Status Page via accidental substrings (already skipped).
    # Bare "pr" is too broad (matches "Deploy to Dev" push titles? no - we match workflow name).
    # But "pr" matches nothing useful alone in workflow names except "PR Validation".
    return any(p in low for p in INCLUDE_WF)


def branch_ok(branch: str) -> bool:
    b = branch or ""
    return b in TRACKED_BRANCHES or b.startswith("routine/")


def list_runs(slug: str, *, limit: int = 50, workflow: str | None = None) -> list[dict]:
    args = [
        "run",
        "list",
        "--repo",
        slug,
        "--limit",
        str(limit),
        "--json",
        "databaseId,status,conclusion,name,workflowName,headBranch,url,createdAt",
    ]
    if workflow:
        args.extend(["--workflow", workflow])
    runs = gh_json(args)
    return runs if isinstance(runs, list) else []


def filter_failures(runs: list[dict]) -> list[dict]:
    out = []
    for run in runs:
        if not branch_ok(run.get("headBranch") or ""):
            continue
        name = wf_name(run)
        if should_skip_wf(name):
            continue
        if not should_include_wf(name):
            continue
        if run.get("conclusion") != "failure":
            continue
        out.append(run)
    return out


def dedupe_runs(runs: list[dict]) -> list[dict]:
    seen: set[int] = set()
    out = []
    for run in runs:
        rid = run.get("databaseId")
        if rid in seen:
            continue
        if rid is not None:
            seen.add(rid)
        out.append(run)
    return out


def scan_repo(slug: str) -> list[dict]:
    collected: list[dict] = []
    # Broad recent window (still filtered)
    collected.extend(filter_failures(list_runs(slug, limit=80)))
    # Explicit critical workflows (survives Status Page flood)
    for wf in CRITICAL_WORKFLOWS.get(slug, []):
        collected.extend(filter_failures(list_runs(slug, limit=10, workflow=wf)))
    # Prefer newest first
    collected = dedupe_runs(collected)
    collected.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
    return collected


def open_autofix_prs(slug: str) -> list[dict]:
    prs = gh_json(
        [
            "pr",
            "list",
            "--repo",
            slug,
            "--state",
            "open",
            "--label",
            "hermes-autofix",
            "--json",
            "number,title,url,headRefName",
        ]
    )
    return prs if isinstance(prs, list) else []


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_failures: list[tuple[str, dict]] = []
    lines = [f"Updated: {stamp}", ""]

    for name, slug in REPOS.items():
        fails = scan_repo(slug)
        prs = open_autofix_prs(slug)
        lines.append(f"### {name} (`{slug}`)")
        if not fails:
            lines.append("- CI: no recent tracked failures")
        else:
            for run in fails[:5]:
                lines.append(
                    f"- FAIL [{wf_name(run)}] "
                    f"branch=`{run.get('headBranch')}` id={run.get('databaseId')} "
                    f"{run.get('url')}"
                )
                all_failures.append((name, run))
        if prs:
            for pr in prs:
                lines.append(f"- open autofix PR #{pr.get('number')}: {pr.get('url')}")
        else:
            lines.append("- open autofix PRs: none")
        lines.append("")

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    updated = replace_section(existing, "CI scan", "\n".join(lines))
    _atomic_write(pipe, updated)

    if all_failures:
        # Telegram + wake autofix — something needs attention
        print("Pipeline scan: failures detected")
        print(f"Failures: {len(all_failures)}")
        for name, run in all_failures[:15]:
            print(
                f"- {name}: {wf_name(run)} on {run.get('headBranch')} "
                f"→ {run.get('url')}"
            )
        print("NEW_FAILURES=1")
        print(json.dumps({"wakeAgent": True}))
        status = "ok"
        summary = f"Scan complete; {len(all_failures)} actionable failure(s); waking autofix"
    else:
        # Silent tick — only the wakeAgent gate line (Hermes suppresses delivery)
        print(json.dumps({"wakeAgent": False}))
        status = "silent"
        summary = "Scan complete; no actionable failures"
    try:
        from ops_audit import append_event

        arts = [str(BRAIN_DIR / "PIPELINES.md")]
        arts.extend(run.get("url") for _, run in all_failures[:5] if run.get("url"))
        append_event(
            job_id="026c0a4c82b7",
            name="CI scan + autofix gate",
            status=status,
            summary=summary,
            detail="\n".join(
                f"{n}: {run.get('workflowName')} {run.get('url')}"
                for n, run in all_failures[:8]
            ),
            artifacts=arts,
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
