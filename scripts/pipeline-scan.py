#!/usr/bin/env python3
"""Scan main/dev/qa CI for wired repos; write brain/PIPELINES.md; wakeAgent gate.

Important: high-frequency workflows (Status Page) can push real failures out of
`gh run list --limit N`. We therefore (1) skip noise workflows, (2) require
include-pattern match for autofix wake, and (3) explicitly poll critical
workflows per repo (from ops-config critical_workflows).

Also classifies open `hermes-autofix` / `hermes-exec` PR checks so the CI
autofix agent can amend red PRs (≤1 attempt/UTC day) or HITL when still red.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR  # noqa: E402
from brain_write import _atomic_write, replace_section  # noqa: E402
from gh_ops import (  # noqa: E402
    LABEL_AUTOFIX,
    LABEL_EXEC,
    LABEL_NEEDS_APPROVAL,
    apply_token_env,
    pr_checks,
)

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

# Agent appends this marker (UTC date) when amending a red Hermes PR.
# Prefer HERMES_PR_AMEND; HERMES_AUTOFIX_AMEND still accepted.
AMEND_MARKER_RE = re.compile(
    r"HERMES_(?:PR_|AUTOFIX_)?AMEND:\s*(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
HERMES_PR_LABELS = (LABEL_AUTOFIX, LABEL_EXEC)

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


def open_hermes_prs(slug: str) -> list[dict]:
    """Open PRs labeled hermes-autofix and/or hermes-exec (deduped by number)."""
    by_num: dict[int, dict] = {}
    fields = "number,title,url,headRefName,isDraft,labels,body"
    for label in HERMES_PR_LABELS:
        prs = gh_json(
            [
                "pr",
                "list",
                "--repo",
                slug,
                "--state",
                "open",
                "--label",
                label,
                "--json",
                fields,
            ]
        )
        if not isinstance(prs, list):
            continue
        for pr in prs:
            num = pr.get("number")
            if num is not None:
                by_num[int(num)] = pr
    return [by_num[k] for k in sorted(by_num)]


# Back-compat alias for tests / callers
open_autofix_prs = open_hermes_prs


def _label_names(pr: dict) -> set[str]:
    return {
        ((lab.get("name") if isinstance(lab, dict) else lab) or "").lower()
        for lab in (pr.get("labels") or [])
    }


def pr_kind(pr: dict) -> str:
    labels = _label_names(pr)
    if LABEL_AUTOFIX in labels:
        return "autofix"
    if LABEL_EXEC in labels:
        return "exec"
    return "hermes"


def last_amend_date(body: str | None) -> str | None:
    """UTC date string from HERMES_PR_AMEND / HERMES_AUTOFIX_AMEND marker, if any."""
    matches = AMEND_MARKER_RE.findall(body or "")
    return matches[-1] if matches else None


def classify_hermes_pr(slug: str, pr: dict, today_utc: str) -> dict:
    """Classify an open hermes-autofix/hermes-exec PR for PIPELINES + wake gating.

    Returns keys: number, url, kind, state, action, detail
      state: draft|hold|pass|fail|pending|unknown
      action: none|amend|hitl|wait
    """
    num = pr.get("number")
    url = pr.get("url") or ""
    kind = pr_kind(pr)
    base = {
        "number": num,
        "url": url,
        "title": pr.get("title") or "",
        "kind": kind,
    }

    if pr.get("isDraft"):
        return {**base, "state": "draft", "action": "none", "detail": "draft"}

    labels = _label_names(pr)
    if LABEL_NEEDS_APPROVAL in labels or "needs-approval" in labels:
        return {
            **base,
            "state": "hold",
            "action": "none",
            "detail": f"label {LABEL_NEEDS_APPROVAL}",
        }

    status, check_detail = pr_checks(slug, int(num))
    detail_s = "; ".join(check_detail[:6]) if check_detail else status
    amended = last_amend_date(pr.get("body"))

    if status == "pass":
        return {**base, "state": "pass", "action": "none", "detail": detail_s}
    if status == "pending":
        return {**base, "state": "pending", "action": "wait", "detail": detail_s}
    if status != "fail":
        return {**base, "state": "unknown", "action": "wait", "detail": detail_s}

    # Red checks: one amend per UTC day, then HITL
    if amended == today_utc:
        return {
            **base,
            "state": "fail",
            "action": "hitl",
            "detail": f"amended {amended}; still red — {detail_s}",
        }
    return {
        **base,
        "state": "fail",
        "action": "amend",
        "detail": detail_s,
        "last_amend": amended,
    }


# Back-compat alias
classify_autofix_pr = classify_hermes_pr


def main() -> int:
    apply_token_env()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    today_utc = now.strftime("%Y-%m-%d")
    all_failures: list[tuple[str, dict]] = []
    red_amend: list[tuple[str, dict]] = []
    red_hitl: list[tuple[str, dict]] = []
    lines = [f"Updated: {stamp}", ""]

    for name, slug in REPOS.items():
        fails = scan_repo(slug)
        prs = open_hermes_prs(slug)
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
                info = classify_hermes_pr(slug, pr, today_utc)
                action = info["action"]
                state = info["state"]
                kind = info.get("kind") or "hermes"
                num = info["number"]
                url = info["url"]
                if action == "amend":
                    lines.append(
                        f"- open {kind} PR #{num} RED amend-eligible: {url}"
                    )
                    red_amend.append((name, info))
                elif action == "hitl":
                    lines.append(
                        f"- open {kind} PR #{num} RED amend-exhausted (HITL): {url}"
                    )
                    red_hitl.append((name, info))
                else:
                    lines.append(
                        f"- open {kind} PR #{num} {state}: {url}"
                    )
        else:
            lines.append("- open hermes-autofix/hermes-exec PRs: none")
        lines.append("")

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    updated = replace_section(existing, "CI scan", "\n".join(lines))
    _atomic_write(pipe, updated)

    wake = bool(all_failures or red_amend or red_hitl)
    if wake:
        print("Pipeline scan: actionable work detected")
        if all_failures:
            print(f"Branch CI failures: {len(all_failures)}")
            for name, run in all_failures[:15]:
                print(
                    f"- {name}: {wf_name(run)} on {run.get('headBranch')} "
                    f"→ {run.get('url')}"
                )
            print("NEW_FAILURES=1")
        if red_amend:
            print(f"Red hermes PRs (amend): {len(red_amend)}")
            for name, info in red_amend:
                print(
                    f"- AMEND {name}#{info['number']} [{info.get('kind')}]: "
                    f"{info['url']} — {info.get('detail', '')}"
                )
            print("RED_AUTOFIX_AMEND=1")
            print("RED_HERMES_AMEND=1")
        if red_hitl:
            print(f"Red hermes PRs (HITL): {len(red_hitl)}")
            for name, info in red_hitl:
                print(
                    f"- HITL {name}#{info['number']} [{info.get('kind')}]: "
                    f"{info['url']} — {info.get('detail', '')}"
                )
            print("RED_AUTOFIX_HITL=1")
            print("RED_HERMES_HITL=1")
        print(
            json.dumps(
                {
                    "wakeAgent": True,
                    "branchFailures": len(all_failures),
                    "redAutofixAmend": len(red_amend),
                    "redAutofixHitl": len(red_hitl),
                    "redHermesAmend": len(red_amend),
                    "redHermesHitl": len(red_hitl),
                }
            )
        )
        status = "ok"
        parts = []
        if all_failures:
            parts.append(f"{len(all_failures)} branch failure(s)")
        if red_amend:
            parts.append(f"{len(red_amend)} red hermes amend")
        if red_hitl:
            parts.append(f"{len(red_hitl)} red hermes HITL")
        summary = f"Scan complete; {'; '.join(parts)}; waking autofix"
    else:
        # Silent tick — only the wakeAgent gate line (Hermes suppresses delivery)
        print(json.dumps({"wakeAgent": False}))
        status = "silent"
        summary = "Scan complete; no actionable failures"
    try:
        from ops_audit import append_event

        arts = [str(BRAIN_DIR / "PIPELINES.md")]
        arts.extend(run.get("url") for _, run in all_failures[:5] if run.get("url"))
        arts.extend(info.get("url") for _, info in (red_amend + red_hitl)[:5] if info.get("url"))
        detail_bits = [
            f"{n}: {run.get('workflowName')} {run.get('url')}"
            for n, run in all_failures[:8]
        ]
        detail_bits.extend(
            f"{n}#{info['number']} {info['action']}: {info['url']}"
            for n, info in (red_amend + red_hitl)[:8]
        )
        append_event(
            job_id="026c0a4c82b7",
            name="CI scan + autofix gate",
            status=status,
            summary=summary,
            detail="\n".join(detail_bits),
            artifacts=arts,
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
