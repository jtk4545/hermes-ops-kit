#!/usr/bin/env python3
"""Shared GitHub CLI helpers (token routing, PR policy, and model attribution)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Prefer dedicated bot token when set; otherwise fall through to ambient `gh` auth.
TOKEN_ENV = "HERMES_GH_TOKEN"

# Labels Hermes manages
LABEL_AUTOFIX = "hermes-autofix"
LABEL_EXEC = "hermes-exec"
LABEL_NEEDS_APPROVAL = "hermes-needs-approval"
LABEL_APPROVED = "hermes-approved"
MODEL_LABEL_PREFIX = "model:"
MODEL_LABEL_COLOR = "5319E7"

try:
    from ops_config import repo_slugs as _repo_slugs
    REPOS = _repo_slugs()
except Exception:
    REPOS = []

YES_COMMENT_PREFIXES = (
    "yes",
    "yes merge",
    "lgtm",
    "approve",
    "approved",
    ":shipit:",
)

def apply_token_env() -> str | None:
    """If HERMES_GH_TOKEN is set, export it as GH_TOKEN for subprocesses.

    Returns the source label used: 'HERMES_GH_TOKEN', 'GH_TOKEN', or None (gh login).
    """
    hermes = os.environ.get(TOKEN_ENV, "").strip()
    if hermes:
        os.environ["GH_TOKEN"] = hermes
        os.environ["GITHUB_TOKEN"] = hermes
        return TOKEN_ENV
    if os.environ.get("GH_TOKEN", "").strip():
        return "GH_TOKEN"
    return None


def gh(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    apply_token_env()
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def gh_json(args: list[str], timeout: int = 90) -> Any | None:
    r = gh(args, timeout=timeout)
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def whoami() -> str:
    r = gh(["api", "user", "--jq", ".login"])
    login = (r.stdout or "").strip()
    if login and r.returncode == 0:
        return login
    return "unknown"


def pr_checks(slug: str, number: int) -> tuple[str, list[str]]:
    """Return (pass|fail|pending|unknown, detail lines)."""
    data = gh_json(
        ["pr", "checks", str(number), "--repo", slug, "--json", "name,state,bucket"]
    )
    if not isinstance(data, list):
        r = gh(["pr", "checks", str(number), "--repo", slug], timeout=60)
        if r.returncode != 0:
            return "unknown", []
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        low = "\n".join(lines).lower()
        if "fail" in low:
            return "fail", lines[:12]
        if lines and all(
            ("pass" in ln.lower()) or ("skip" in ln.lower()) or ("neutral" in ln.lower())
            for ln in lines
        ):
            return "pass", lines[:12]
        return "pending", lines[:12]

    details = [f"{c.get('name')}:{c.get('bucket') or c.get('state')}" for c in data]
    states = [(c.get("bucket") or c.get("state") or "").lower() for c in data]
    if any(s in ("fail", "failure") for s in states):
        return "fail", details
    if states and all(s in ("pass", "success", "skip", "neutral") for s in states):
        return "pass", details
    return "pending", details


def _label_names(pr: dict) -> set[str]:
    return {
        ((lab.get("name") if isinstance(lab, dict) else lab) or "").lower()
        for lab in (pr.get("labels") or [])
    }


def pr_has_yes_comment(slug: str, number: int) -> bool:
    """True if a PR issue comment is an explicit yes/approve (Telegram users can comment on PR)."""
    comments = gh_json(["api", f"repos/{slug}/issues/{number}/comments"])
    if not isinstance(comments, list):
        return False
    for c in comments:
        body = (c.get("body") or "").strip().lower()
        if not body:
            continue
        first = body.splitlines()[0].strip()
        if first in YES_COMMENT_PREFIXES or first.startswith("yes ") or first.startswith("approved"):
            return True
    return False


def is_explicitly_approved(slug: str, pr: dict) -> tuple[bool, str]:
    """Human cleared the hold via label, approving review, or yes comment."""
    labels = _label_names(pr)
    if LABEL_APPROVED in labels:
        return True, f"label {LABEL_APPROVED}"
    review = (pr.get("reviewDecision") or "").upper()
    if review == "APPROVED":
        return True, "reviewDecision=APPROVED"
    num = pr.get("number")
    if num is not None and pr_has_yes_comment(slug, int(num)):
        return True, "PR comment yes/approve"
    return False, ""


def needs_human_approval(pr: dict, slug: str | None = None) -> tuple[bool, str]:
    """Decide if green merge must wait for human APPROVAL.

    Explicit approval (hermes-approved / APPROVED review / yes comment) clears the hold.
    """
    labels = _label_names(pr)
    if slug:
        ok, why = is_explicitly_approved(slug, pr)
        if ok:
            return False, ""

    if LABEL_APPROVED in labels:
        return False, ""

    if LABEL_NEEDS_APPROVAL in labels or "needs-approval" in labels:
        return True, f"label {LABEL_NEEDS_APPROVAL}"

    blob = f"{pr.get('title') or ''}\n{pr.get('body') or ''}".upper()
    if "HERMES_NEEDS_APPROVAL" in blob or "APPROVAL REQUIRED" in blob:
        # still honor explicit approval above
        return True, "body marker HERMES_NEEDS_APPROVAL"

    review = (pr.get("reviewDecision") or "").upper()
    if review == "CHANGES_REQUESTED":
        return True, "reviewDecision=CHANGES_REQUESTED"

    # Branch protection: reviews still required — ping human instead of spinning
    mss = (pr.get("mergeStateStatus") or "").upper()
    if mss == "BLOCKED" and review == "REVIEW_REQUIRED":
        return True, "branch protection requires review"

    return False, ""


def try_merge(slug: str, number: int) -> str:
    """Enable auto-merge (squash) when possible; fall back to immediate merge."""
    r = gh(
        [
            "pr",
            "merge",
            str(number),
            "--repo",
            slug,
            "--auto",
            "--squash",
            "--delete-branch",
        ],
        timeout=90,
    )
    if r.returncode == 0:
        return "auto-merge enabled/completed (squash)"
    # Already mergeable now — merge immediately
    r2 = gh(
        [
            "pr",
            "merge",
            str(number),
            "--repo",
            slug,
            "--squash",
            "--delete-branch",
        ],
        timeout=90,
    )
    if r2.returncode == 0:
        return "merged (squash)"
    err = (r2.stderr or r.stderr or r2.stdout or r.stdout or "merge failed")[:240]
    return f"merge failed: {err}"


def ensure_label(slug: str, name: str, color: str = "0E8A16") -> None:
    """Best-effort create label (ignore errors if exists / no perm)."""
    gh(
        [
            "label",
            "create",
            name,
            "--repo",
            slug,
            "--color",
            color,
            "--force",
        ],
        timeout=30,
    )


def sanitize_model_token(value: str) -> str:
    """Return a stable GitHub-label-safe model token."""
    token = (value or "").strip().lower().replace(" ", "-")
    token = re.sub(r"[^a-z0-9._+-]+", "-", token)
    token = re.sub(r"-{2,}", "-", token).strip("-._")
    return token[:40] or "unknown"


def model_label(model: str) -> str:
    return f"{MODEL_LABEL_PREFIX}{sanitize_model_token(model)}"


def detect_active_model(
    model: str | None = None,
    provider: str | None = None,
) -> tuple[str, str]:
    """Detect the model opening a PR without relying on one runtime version."""
    found_model = (
        (model or "").strip()
        or os.environ.get("HERMES_ACTIVE_MODEL", "").strip()
        or os.environ.get("HERMES_MODEL", "").strip()
    )
    found_provider = (
        (provider or "").strip()
        or os.environ.get("HERMES_ACTIVE_PROVIDER", "").strip()
        or os.environ.get("HERMES_PROVIDER", "").strip()
    )

    job_id = os.environ.get("HERMES_CRON_JOB_ID", "").strip()
    if job_id and (not found_model or not found_provider):
        try:
            from hermes_paths import hermes_home

            jobs_path = hermes_home() / "cron" / "jobs.json"
            data = json.loads(jobs_path.read_text(encoding="utf-8"))
            jobs = data if isinstance(data, list) else data.get("jobs", [])
            job = next(
                (
                    entry
                    for entry in jobs
                    if isinstance(entry, dict) and str(entry.get("id") or "") == job_id
                ),
                {},
            )
            found_model = found_model or str(
                job.get("model") or job.get("model_snapshot") or ""
            ).strip()
            found_provider = found_provider or str(
                job.get("provider") or job.get("provider_snapshot") or ""
            ).strip()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return found_provider or "unknown", found_model or "unknown"


def append_model_footer(body: str, provider: str, model: str) -> str:
    marker = "<!-- hermes-model:"
    if marker in (body or ""):
        return body
    footer = (
        "\n\n---\n"
        f"**Hermes-Model:** `{provider}` / `{model}`\n"
        f"<!-- hermes-model: {provider}/{model} -->\n"
    )
    return (body or "").rstrip() + footer


def ensure_model_label(slug: str, model: str) -> str:
    name = model_label(model)
    ensure_label(slug, name, color=MODEL_LABEL_COLOR)
    return name


def create_pr(
    *,
    repo: str,
    title: str,
    body: str = "",
    base: str | None = None,
    head: str | None = None,
    labels: list[str] | None = None,
    draft: bool = False,
    model: str | None = None,
    provider: str | None = None,
    skip_model_tag: bool = False,
) -> tuple[bool, str]:
    """Create a PR with role labels plus model label/footer attribution."""
    provider_id, model_id = detect_active_model(model=model, provider=provider)
    labels = list(labels or [])
    if not skip_model_tag:
        body = append_model_footer(body, provider_id, model_id)
        attribution_label = ensure_model_label(repo, model_id)
        if attribution_label not in labels:
            labels.append(attribution_label)
    for label in labels:
        if label.startswith("hermes-"):
            ensure_label(repo, label)

    args = ["pr", "create", "--repo", repo, "--title", title, "--body", body]
    if base:
        args.extend(["--base", base])
    if head:
        args.extend(["--head", head])
    if draft:
        args.append("--draft")
    for label in labels:
        args.extend(["--label", label])
    result = gh(args, timeout=120)
    output = "\n".join(
        value.strip() for value in (result.stdout or "", result.stderr or "") if value.strip()
    )
    if result.returncode != 0:
        return False, output[:800] or f"gh pr create failed rc={result.returncode}"
    return True, (result.stdout or output).strip()


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes GitHub ops helpers")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("whoami", help="Show gh identity")
    detect = sub.add_parser("detect-model", help="Print detected provider/model")
    detect.add_argument("--model")
    detect.add_argument("--provider")
    create = sub.add_parser("create-pr", help="Create a model-attributed PR")
    create.add_argument("--repo", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--body", default="")
    create.add_argument("--body-file")
    create.add_argument("--base")
    create.add_argument("--head")
    create.add_argument("--label", action="append", default=[])
    create.add_argument("--draft", action="store_true")
    create.add_argument("--model")
    create.add_argument("--provider")
    create.add_argument("--skip-model-tag", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd in (None, "whoami"):
        src = apply_token_env()
        print(f"token_source={src or 'gh login'}")
        print(f"login={whoami()}")
        return 0
    if args.cmd == "detect-model":
        provider_id, model_id = detect_active_model(args.model, args.provider)
        print(f"{provider_id}/{model_id}")
        print(model_label(model_id))
        return 0
    if args.cmd == "create-pr":
        body = args.body
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        ok, message = create_pr(
            repo=args.repo,
            title=args.title,
            body=body,
            base=args.base,
            head=args.head,
            labels=args.label,
            draft=args.draft,
            model=args.model,
            provider=args.provider,
            skip_model_tag=args.skip_model_tag,
        )
        print(message)
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
