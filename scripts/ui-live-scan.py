#!/usr/bin/env python3
"""Nightly UI + live quality scan → PIPELINES + wakeAgent for hermes-autofix.

Track B of the Hermes UI quality loop:
  1) Poll GitHub Actions for e2e/playwright/nightly failures on tracked branches
  2) Optionally run tether pytest -m critical locally (HERMES_UI_LIVE_RUN=1)
  3) Optionally run live Playwright tracers against BASE_URL env targets

Env (optional local live runs):
  HERMES_UI_LIVE_RUN=1          — execute local suites (default: scan GHA only)
  HERMES_PROJECTS_ROOT          — default: home directory
  HERMES_LIVE_ADMIN_URL         — optional live URL (also live_urls.json)
  HERMES_LIVE_AEDIF_URL
  HERMES_LIVE_STREAMING_URL
  HERMES_LIVE_NTVIEWER_URL
  HERMES_LIVE_TETHER_SITE_URL
  HERMES_LIVE_PAXDEV_URL
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR  # noqa: E402
from brain_write import _atomic_write, replace_section  # noqa: E402

BASE = Path(os.environ.get("HERMES_PROJECTS_ROOT", str(Path.home())))
LIVE_URLS_FILE = Path(__file__).resolve().parent / "live_urls.json"

# Dev defaults (overridable via env or live_urls.json)
DEFAULT_LIVE_URLS: dict[str, str] = {}


def load_live_url(env_key: str) -> str:
    """Resolve live URL: process env → User env → live_urls.json → DEFAULT_LIVE_URLS."""
    val = (os.environ.get(env_key) or "").strip()
    if val:
        return val
    try:
        user_val = os.environ.get(env_key)  # already checked
        if not user_val and sys.platform == "win32":
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
    if LIVE_URLS_FILE.is_file():
        try:
            data = json.loads(LIVE_URLS_FILE.read_text(encoding="utf-8"))
            file_val = (data.get(env_key) or "").strip()
            if file_val:
                return file_val
        except (OSError, json.JSONDecodeError):
            pass
    return (DEFAULT_LIVE_URLS.get(env_key) or "").strip()

REPOS = {
    "tether": "paladin-io/tether",
    "ntviewer": "paladin-io/ntviewer",
    "paladin-streaming": "paladin-io/paladin-streaming",
    "aedif-ai": "paladin-io/aedif-ai",
    "tether-site": "paladin-io/tether-site",
}

TRACKED_BRANCHES = {"main", "trunk", "dev", "qa", "routine/qa-loop"}

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

CRITICAL_WORKFLOWS: dict[str, list[str]] = {
    "paladin-io/tether": ["Nightly E2E", "PR Validation", "Deploy to Dev"],
    "paladin-io/aedif-ai": ["CI"],
    "paladin-io/paladin-streaming": ["CI"],
    "paladin-io/ntviewer": ["CI"],
    "paladin-io/tether-site": ["CI"],
}

LIVE_PW_TARGETS = [
    {
        "name": "tether-admin",
        "env": "HERMES_LIVE_ADMIN_URL",
        "cwd": BASE / "tether" / "admin_portal",
        "cmd": ["npx", "playwright", "test", "e2e/journeys/live-admin.journey.spec.ts"],
    },
    {
        "name": "aedif-ai",
        "env": "HERMES_LIVE_AEDIF_URL",
        "cwd": BASE / "aedif-ai",
        "cmd": ["npm", "run", "test:e2e:tracers"],
    },
    {
        "name": "paladin-streaming",
        "env": "HERMES_LIVE_STREAMING_URL",
        "cwd": BASE / "paladin-streaming" / "frontend",
        "cmd": ["npm", "run", "test:e2e:tracers"],
        "extra_env": {"PALADIN_E2E_LIVE": "1"},
    },
    {
        "name": "ntviewer",
        "env": "HERMES_LIVE_NTVIEWER_URL",
        "cwd": BASE / "ntviewer" / "app",
        "cmd": ["npm", "run", "test:e2e:tracers"],
    },
    {
        "name": "tether-site",
        "env": "HERMES_LIVE_TETHER_SITE_URL",
        "cwd": BASE / "tether-site" / "tether",
        "cmd": ["npm", "run", "test:e2e:tracers"],
    },
]

# Lightweight HTTP landing checks (no Playwright). Used for marketing pages.
LIVE_HTTP_LANDINGS = [
    {
        "name": "paxdev-landing",
        "env": "HERMES_LIVE_PAXDEV_URL",
        # Primary waitlist CTA + product name must appear in HTML body.
        "must_contain": ("Paxdev", "Waitlist", "waitlist"),
        "ok_statuses": (200,),
    },
    {
        "name": "aedif-canary",
        "env": "HERMES_LIVE_AEDIF_URL",
        "must_contain": ("Aedif", "Schematic"),
        "ok_statuses": (200,),
        # Canary cert may be untrusted on agent hosts; still prove reachability.
        "insecure": True,
    },
]

JOB_ID = "h11uilive23"


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


def run_tether_critical() -> tuple[str, bool, str]:
    """Returns (label, failed, detail)."""
    tether = BASE / "tether"
    if not tether.is_dir():
        return "tether pytest critical", False, "skip: tether checkout missing"
    # Deploy-gate critical markers, then golden-path routing expansion (Slack↔Teams/Discord).
    cmds = [
        (
            "tether pytest critical",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/e2e_tests/",
                "-m",
                "critical",
                "-v",
                "--timeout=180",
            ],
        ),
        (
            "tether pytest routing tracers",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/e2e_tests/test_critical_routing.py",
                "tests/e2e_tests/test_critical_slack_discord.py",
                "-v",
                "--timeout=180",
            ],
        ),
    ]
    details: list[str] = []
    any_fail = False
    for label, cmd in cmds:
        code, out = run_cmd(cmd, cwd=tether, timeout=1200)
        failed = code != 0
        low = out.lower()
        if failed and any(
            x in low
            for x in (
                "secret",
                "not configured",
                "skipped",
                "no module named",
                "credentials",
            )
        ) and " failed" not in low:
            details.append(f"{label}: env/skip (code={code})")
            continue
        if failed:
            any_fail = True
            details.append(f"{label}: FAIL {out[-400:]}")
        else:
            details.append(f"{label}: ok")
    return "tether pytest critical+routing", any_fail, "; ".join(details)

def run_live_playwright() -> list[tuple[str, bool, str]]:
    """Returns list of (label, failed, detail)."""
    results: list[tuple[str, bool, str]] = []
    for target in LIVE_PW_TARGETS:
        url = load_live_url(target["env"])
        if not url:
            results.append((target["name"], False, f"skip: {target['env']} unset"))
            continue
        cwd: Path = target["cwd"]
        if not cwd.is_dir():
            results.append((target["name"], False, f"skip: missing {cwd}"))
            continue
        env = {
            "PLAYWRIGHT_BASE_URL": url,
            "PLAYWRIGHT_NO_WEBSERVER": "1",
            target["env"]: url,
        }
        env.update(target.get("extra_env") or {})
        if target["name"] == "paladin-streaming":
            env["PALADIN_E2E_BASE_URL"] = url
        if target["name"] == "tether-admin":
            env["HERMES_LIVE_ADMIN_URL"] = url
        code, out = run_cmd(target["cmd"], cwd=cwd, env=env, timeout=900)
        results.append(
            (
                target["name"] + " live PW",
                code != 0,
                out[-800:] if code else f"ok ({url})",
            )
        )
    return results


def check_http_landing(
    url: str,
    *,
    must_contain: tuple[str, ...] | list[str] = (),
    ok_statuses: tuple[int, ...] = (200,),
    timeout: float = 15.0,
    insecure: bool = False,
) -> tuple[bool, str]:
    """GET landing URL; require HTTP status and optional body substrings.

    Returns (failed, detail). failed=False means healthy or intentional skip.
    When insecure=True, TLS certificate verification is disabled (canary/dev hosts).
    """
    url = (url or "").strip()
    if not url:
        return False, "skip: empty url"
    import ssl
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "hermes-ui-live-scan/1.0"},
        method="GET",
    )
    open_kwargs: dict = {"timeout": timeout}
    if insecure:
        open_kwargs["context"] = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, **open_kwargs) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read(200_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code} for {url}"
    except Exception as exc:  # noqa: BLE001 — surface any fetch failure
        return True, f"fetch failed for {url}: {exc}"

    if status not in ok_statuses:
        return True, f"unexpected status {status} for {url}"
    missing = [s for s in must_contain if s and s not in body]
    if missing:
        return True, f"missing body markers {missing} at {url}"
    return False, f"ok ({url} HTTP {status})"


def run_paxdev_cursor_smoke() -> tuple[str, bool, str]:
    """Cursor editor+agent loop — landing HTTP is not the product UI."""
    try:
        from paxdev_cursor_ui_smoke import run_smoke
    except ImportError:
        return "paxdev-cursor-editor-agent", False, "skip: paxdev_cursor_ui_smoke.py missing"
    result = run_smoke()
    failed = not bool(result.get("ok"))
    return "paxdev-cursor-editor-agent", failed, str(result.get("summary") or "")


def run_live_http_landings() -> list[tuple[str, bool, str]]:
    """Returns list of (label, failed, detail) for LIVE_HTTP_LANDINGS."""
    results: list[tuple[str, bool, str]] = []
    for target in LIVE_HTTP_LANDINGS:
        url = load_live_url(target["env"])
        if not url:
            results.append((target["name"], False, f"skip: {target['env']} unset"))
            continue
        failed, detail = check_http_landing(
            url,
            must_contain=tuple(target.get("must_contain") or ()),
            ok_statuses=tuple(target.get("ok_statuses") or (200,)),
            insecure=bool(target.get("insecure")),
        )
        results.append((target["name"] + " HTTP", failed, detail))
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
    local_run = os.environ.get("HERMES_UI_LIVE_RUN", "").strip() in {"1", "true", "yes"}

    gha_failures: list[tuple[str, dict]] = []
    local_failures: list[tuple[str, str, str]] = []  # name, class, detail

    lines = [f"Updated: {stamp}", f"Local live run: {local_run}", ""]

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

    lines.append("### Editor / agent UI")
    label, failed, detail = run_paxdev_cursor_smoke()
    cls = classify_failure_detail(detail) if failed else "ok"
    skip = str(detail).startswith("skip:")
    lines.append(
        f"- {label}: {'FAIL' if failed else ('skip' if skip else 'ok')} ({cls}) {detail[:240]}"
    )
    if failed:
        local_failures.append((label, cls, detail))
    lines.append("")

    if local_run:
        lines.append("### Local live suites")
        label, failed, detail = run_tether_critical()
        cls = classify_failure_detail(detail) if failed else "ok"
        lines.append(f"- {label}: {'FAIL' if failed else 'ok'} ({cls})")
        if failed:
            local_failures.append((label, cls, detail))
            lines.append(f"  detail: {detail[:300].replace(chr(10), ' ')}")
        for label, failed, detail in run_live_playwright():
            cls = classify_failure_detail(detail) if failed else "ok"
            lines.append(
                f"- {label}: {'FAIL' if failed else detail if detail.startswith('skip') else 'ok'} ({cls})"
            )
            if failed:
                local_failures.append((label, cls, detail))
        for label, failed, detail in run_live_http_landings():
            cls = classify_failure_detail(detail) if failed else "ok"
            lines.append(
                f"- {label}: {'FAIL' if failed else detail if detail.startswith('skip') else 'ok'} ({cls})"
            )
            if failed:
                local_failures.append((label, cls, detail))
        lines.append("")

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    updated = replace_section(existing, "UI live scan", "\n".join(lines))
    _atomic_write(pipe, updated)

    # Wake autofix for GHA failures and product/selector local failures (not pure env skips)
    actionable_local = [
        (n, c, d)
        for n, c, d in local_failures
        if c in {"product_or_unknown", "brittle_selector"}
    ]
    env_blocks = [(n, c, d) for n, c, d in local_failures if c in {"env_secret", "flake_or_env"}]

    wake = bool(gha_failures or actionable_local)

    if wake:
        print("UI live scan: actionable failures")
        print(f"GHA failures: {len(gha_failures)}; local product/selector: {len(actionable_local)}")
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
