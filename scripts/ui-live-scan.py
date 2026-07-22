#!/usr/bin/env python3
"""Nightly UI + live quality scan → PIPELINES + wakeAgent for hermes-autofix.

Track B of the Hermes UI quality loop:
  1) Poll GitHub Actions for e2e/playwright/nightly failures on tracked branches
  2) Optionally run local checks from ops-config ui_live.local_checks[] (HERMES_UI_LIVE_RUN=1)
  3) Live base URLs from HERMES_LIVE_* env or $HERMES_HOME/scripts/live_urls.json

Env (optional local live runs):
  HERMES_UI_LIVE_RUN=1          — execute local suites (default: scan GHA only)
  HERMES_PROJECTS_ROOT          — checkout root (from ops-config projects_root)
  HERMES_LIVE_*                 — live base URLs (also live_urls.json)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR, HERMES_HOME  # noqa: E402
from brain_write import _atomic_write, replace_section  # noqa: E402

try:
    from ops_config import (
        critical_workflows,
        load_config,
        projects_root,
        repo_name_map,
        ui_live_settings,
    )

    _CFG = load_config()
    REPOS = repo_name_map(_CFG)
    CRITICAL_WORKFLOWS = critical_workflows(_CFG)
    TRACKED_BRANCHES = set(
        _CFG.get("tracked_branches") or ["main", "trunk", "dev", "qa"]
    )
    BASE = projects_root(_CFG)
    # Top-level ui_live.{enabled,local_checks} — not models.ui_live
    UI_LIVE = ui_live_settings(_CFG)
except Exception:
    REPOS = {}
    CRITICAL_WORKFLOWS = {}
    TRACKED_BRANCHES = {"main", "trunk", "dev", "qa"}
    BASE = Path(os.environ.get("HERMES_PROJECTS_ROOT") or Path.home())
    UI_LIVE = {}
    _CFG = {}

LIVE_URLS_CANDIDATES = [
    HERMES_HOME / "scripts" / "live_urls.json",
    HERMES_HOME / "scripts" / "live_urls.example.json",
    Path(__file__).resolve().parent.parent / "templates" / "live_urls.example.json",
]

# Workflow name substrings that count as UI/live actionable
INCLUDE_WF = (
    "e2e",
    "playwright",
    "nightly",
    "frontend — e2e",
    "site playwright",
)

SKIP_WF = (
    "release",
    "prod",
    "production",
    "hotfix",
    "status page",
    "dependabot",
)

JOB_ID = "h11uilive23"


def _load_live_urls_file() -> dict:
    for path in LIVE_URLS_CANDIDATES:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def load_live_url(env_key: str) -> str:
    """Resolve live URL: process env → User env (Windows) → live_urls.json."""
    val = (os.environ.get(env_key) or "").strip()
    if val:
        return val
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                try:
                    user_val, _ = winreg.QueryValueEx(key, env_key)
                    if user_val and str(user_val).strip():
                        return str(user_val).strip()
                except FileNotFoundError:
                    pass
    except Exception:
        pass
    file_val = (_load_live_urls_file().get(env_key) or "").strip()
    return file_val


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
    return any(p in low for p in INCLUDE_WF)


def branch_ok(branch: str) -> bool:
    b = branch or ""
    return b in TRACKED_BRANCHES or b.startswith("routine/")


def list_runs(slug: str, *, limit: int = 40, workflow: str | None = None) -> list[dict]:
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
    collected.extend(filter_failures(list_runs(slug, limit=50)))
    for wf in CRITICAL_WORKFLOWS.get(slug, []):
        collected.extend(filter_failures(list_runs(slug, limit=8, workflow=wf)))
    collected = dedupe_runs(collected)
    collected.sort(key=lambda r: r.get("createdAt") or "", reverse=True)
    return collected


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> tuple[int, str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=merged,
            shell=False,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out[-4000:]
    except FileNotFoundError as exc:
        return 127, str(exc)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"


def _resolve_cmd(cmd: list[str]) -> list[str]:
    """Expand simple placeholders used in ui_live.local_checks."""
    mapping = {
        "{python}": sys.executable,
        "{node}": "node",
        "{npm}": "npm",
        "{npx}": "npx",
    }
    return [mapping.get(part, part) for part in cmd]


def run_local_checks() -> list[tuple[str, bool, str]]:
    """Run config-driven local checks. Returns (label, failed, detail)."""
    results: list[tuple[str, bool, str]] = []
    checks = UI_LIVE.get("local_checks") or []
    if not isinstance(checks, list):
        return results

    for raw in checks:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("name") or "local check")
        url_env = str(raw.get("url_env") or raw.get("env") or "").strip()
        url = load_live_url(url_env) if url_env else ""
        if url_env and not url:
            results.append((label, False, f"skip: {url_env} unset"))
            continue

        rel = str(raw.get("cwd") or raw.get("path") or ".")
        cwd = Path(rel)
        if not cwd.is_absolute():
            cwd = BASE / rel
        if not cwd.is_dir():
            results.append((label, False, f"skip: missing {cwd}"))
            continue

        cmd = raw.get("cmd") or raw.get("command") or []
        if isinstance(cmd, str):
            cmd = cmd.split()
        cmd = _resolve_cmd([str(c) for c in cmd])
        if not cmd:
            results.append((label, False, "skip: empty cmd"))
            continue

        env: dict[str, str] = {}
        if url:
            env["PLAYWRIGHT_BASE_URL"] = url
            env["PLAYWRIGHT_NO_WEBSERVER"] = "1"
            if url_env:
                env[url_env] = url
            for key in raw.get("base_url_env_keys") or []:
                env[str(key)] = url
        extra = raw.get("extra_env") or {}
        if isinstance(extra, dict):
            env.update({str(k): str(v) for k, v in extra.items()})

        timeout = int(raw.get("timeout") or 900)
        code, out = run_cmd(cmd, cwd=cwd, env=env or None, timeout=timeout)
        low = out.lower()
        if code != 0 and any(
            x in low
            for x in (
                "secret",
                "not configured",
                "skipped",
                "no module named",
                "credentials",
            )
        ) and " failed" not in low:
            results.append((label, False, f"env/skip (code={code})"))
            continue
        results.append(
            (
                label,
                code != 0,
                out[-800:] if code else (f"ok ({url})" if url else "ok"),
            )
        )
    return results


def classify_failure_detail(detail: str) -> str:
    low = (detail or "").lower()
    if any(x in low for x in ("secret", "credential", "not configured", "403", "401")):
        return "env_secret"
    if any(x in low for x in ("timeout", "flake", "net::", "econnrefused")):
        return "flake_or_env"
    if any(x in low for x in ("locator", "strict mode", "selector", "tobevisible")):
        return "brittle_selector"
    return "product_or_unknown"


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if UI_LIVE and UI_LIVE.get("enabled") is False:
        # Explicit disable; still allow GHA scan unless caller wants full off
        pass

    local_run = os.environ.get("HERMES_UI_LIVE_RUN", "").strip() in {"1", "true", "yes"}

    gha_failures: list[tuple[str, dict]] = []
    local_failures: list[tuple[str, str, str]] = []

    lines = [f"Updated: {stamp}", f"Local live run: {local_run}", ""]

    if not REPOS:
        lines.append("No repos configured in ops-config github.repos")
        lines.append("")

    for name, slug in REPOS.items():
        fails = scan_repo(slug)
        lines.append(f"### {name} (`{slug}`)")
        if not fails:
            lines.append("- GHA UI/e2e: no recent tracked failures")
        else:
            for run in fails[:5]:
                lines.append(
                    f"- FAIL [{wf_name(run)}] branch=`{run.get('headBranch')}` "
                    f"id={run.get('databaseId')} {run.get('url')}"
                )
                gha_failures.append((name, run))
        lines.append("")

    if local_run:
        lines.append("### Local live suites")
        checks = run_local_checks()
        if not checks:
            lines.append(
                "- no ui_live.local_checks configured "
                "(add checks in ops-config or skip HERMES_UI_LIVE_RUN)"
            )
        for label, failed, detail in checks:
            cls = classify_failure_detail(detail) if failed else "ok"
            if detail.startswith("skip") or detail.startswith("env/skip"):
                lines.append(f"- {label}: {detail} ({cls})")
            else:
                lines.append(
                    f"- {label}: {'FAIL' if failed else 'ok'} ({cls})"
                )
            if failed:
                local_failures.append((label, cls, detail))
                lines.append(f"  detail: {detail[:300].replace(chr(10), ' ')}")
        lines.append("")

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    updated = replace_section(existing, "UI live scan", "\n".join(lines))
    _atomic_write(pipe, updated)

    actionable_local = [
        (n, c, d)
        for n, c, d in local_failures
        if c in {"product_or_unknown", "brittle_selector"}
    ]
    env_blocks = [
        (n, c, d) for n, c, d in local_failures if c in {"env_secret", "flake_or_env"}
    ]

    wake = bool(gha_failures or actionable_local)

    if wake:
        print("UI live scan: actionable failures")
        print(
            f"GHA failures: {len(gha_failures)}; "
            f"local product/selector: {len(actionable_local)}"
        )
        for name, run in gha_failures[:10]:
            print(f"- GHA {name}: {wf_name(run)} -> {run.get('url')}")
        for name, cls, detail in actionable_local[:10]:
            print(f"- LOCAL {name} [{cls}]: {detail[:200]}")
        print("NEW_FAILURES=1")
        print(json.dumps({"wakeAgent": True}))
        status = "ok"
        summary = (
            f"UI live scan; {len(gha_failures)} GHA + "
            f"{len(actionable_local)} local actionable; waking autofix"
        )
    else:
        if env_blocks:
            print("UI live scan: env/flake blocks only (no autofix wake)")
            for name, cls, detail in env_blocks[:8]:
                print(f"- BLOCK {name} [{cls}]: {detail[:200]}")
            print(json.dumps({"wakeAgent": False}))
            status = "blocked"
            summary = f"UI live scan; {len(env_blocks)} env/flake block(s); no wake"
        else:
            print(json.dumps({"wakeAgent": False}))
            status = "silent"
            summary = "UI live scan; no actionable failures"

    try:
        from ops_audit import append_event

        arts = [str(BRAIN_DIR / "PIPELINES.md")]
        arts.extend(run.get("url") for _, run in gha_failures[:5] if run.get("url"))
        append_event(
            job_id=JOB_ID,
            name="UI live scan gate",
            status=status,
            summary=summary,
            detail="\n".join(
                [f"GHA {n}: {wf_name(r)} {r.get('url')}" for n, r in gha_failures[:6]]
                + [f"LOCAL {n} [{c}]" for n, c, _ in (actionable_local + env_blocks)[:6]]
            ),
            artifacts=arts,
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
