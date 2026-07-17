#!/usr/bin/env python3
"""Monitor open hermes-autofix / hermes-exec PRs; merge on green unless approval needed."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR  # noqa: E402
from brain_write import _atomic_write, replace_section  # noqa: E402
from gh_ops import (  # noqa: E402
    LABEL_APPROVED,
    LABEL_AUTOFIX,
    LABEL_EXEC,
    LABEL_NEEDS_APPROVAL,
    REPOS,
    apply_token_env,
    gh,
    gh_json,
    needs_human_approval,
    pr_checks,
    try_merge,
    whoami,
)

PR_FIELDS = "number,title,url,headRefName,body,labels,reviewDecision,mergeStateStatus,isDraft"


def list_labeled(slug: str, label: str) -> list[dict]:
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
            PR_FIELDS,
        ]
    )
    return prs if isinstance(prs, list) else []


def clear_approval_hold(slug: str, number: int) -> None:
    """Best-effort: drop needs-approval label after explicit yes."""
    gh(["pr", "edit", str(number), "--repo", slug, "--remove-label", LABEL_NEEDS_APPROVAL], timeout=30)


def main() -> int:
    token_src = apply_token_env()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    actor = whoami()
    try:
        from weekend_policy import is_weekend

        weekend = is_weekend()
    except Exception:
        weekend = False
    alerts: list[str] = []
    lines = [
        f"Updated: {stamp}",
        f"gh identity: {actor} (token={token_src or 'gh login'})",
        f"weekend_no_hitl={weekend}",
        "",
    ]

    seen: set[tuple[str, int]] = set()

    for slug in REPOS:
        by_num: dict[int, dict] = {}
        for label in (LABEL_AUTOFIX, LABEL_EXEC):
            for pr in list_labeled(slug, label):
                by_num[pr["number"]] = pr

        if not by_num:
            continue

        lines.append(f"### {slug}")
        for num, pr in sorted(by_num.items()):
            key = (slug, num)
            if key in seen:
                continue
            seen.add(key)

            if pr.get("isDraft"):
                lines.append(f"- PR #{num} `draft` {pr.get('url')}")
                continue

            labels = [
                (lab.get("name") if isinstance(lab, dict) else lab) or ""
                for lab in (pr.get("labels") or [])
            ]
            kind = "exec" if LABEL_EXEC in labels else "autofix"
            status, detail = pr_checks(slug, num)
            approval, why = needs_human_approval(pr, slug=slug)
            lines.append(
                f"- PR #{num} [{kind}] `{status}` approval={approval} {pr.get('url')}"
            )

            if status == "pass":
                if approval:
                    lines.append(f"  - HOLD for human: {why}")
                    if weekend:
                        lines.append(
                            "  - weekend: APPROVAL Telegram suppressed (defer HITL to weekday)"
                        )
                    else:
                        alerts.append(
                            f"APPROVAL NEEDED [{kind}] {slug}#{num} — {why} — {pr.get('url')} "
                            f"(comment `yes` on the PR, add label `{LABEL_APPROVED}`, "
                            f"or remove `{LABEL_NEEDS_APPROVAL}` — monitor merges within 30m)"
                        )
                else:
                    # If hold was cleared by yes/approved, tidy label
                    if LABEL_NEEDS_APPROVAL in {x.lower() for x in labels}:
                        clear_approval_hold(slug, num)
                    msg = try_merge(slug, num)
                    lines.append(f"  - merge: {msg}")
                    if "fail" in msg.lower():
                        alerts.append(
                            f"MERGE FAILED [{kind}] {slug}#{num} — {msg} — {pr.get('url')}"
                        )
                    else:
                        # Success merges stay in PIPELINES/audit — no Telegram spam
                        lines.append("  - (telegram suppressed for successful merge)")
            elif status == "fail":
                alerts.append(f"RED [{kind}] {slug}#{num} — {pr.get('url')}")
                for d in detail[:5]:
                    lines.append(f"  - {d}")
            else:
                lines.append("  - checks still pending")
        lines.append("")

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    body = (
        "\n".join(lines)
        if len(lines) > 3
        else f"Updated: {stamp}\n\ngh identity: {actor}\n\nNo open hermes-autofix/hermes-exec PRs.\n"
    )
    updated = replace_section(existing, "PR monitor", body)
    _atomic_write(pipe, updated)

    if not alerts:
        return 0  # silent — skip audit when nothing happened
    print("PR monitor alerts")
    for a in alerts:
        print(f"- {a}")
    try:
        from ops_audit import append_event

        append_event(
            job_id="b2prmon30m",
            name="PR monitor",
            status="ok",
            summary=f"{len(alerts)} alert(s) (merge/hold/red)",
            detail="\n".join(alerts[:12]),
            artifacts=[str(BRAIN_DIR / "PIPELINES.md")],
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
