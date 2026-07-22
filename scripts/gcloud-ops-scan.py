#!/usr/bin/env python3
"""Read-only GCP ops + cost scan → PIPELINES / COSTS + wakeAgent gate.

Uses gcloud CLI with a dedicated read-only service account
(HERMES_GCLOUD_SA_KEY or GOOGLE_APPLICATION_CREDENTIALS or
$HERMES_HOME/secrets/gcloud-ops.json).

Never deploys, mutates IAM, or reads Secret Manager payloads.
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

JOB_ID = "h12gcloud0730"


def gcloud_exe() -> str:
    """Resolve gcloud for subprocess (Windows uses gcloud.cmd, not the .ps1 shim)."""
    import shutil

    for name in ("gcloud.cmd", "gcloud"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return "gcloud"


GCLOUD = gcloud_exe()


def _read_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_gcloud_config() -> dict:
    """Merge ops-config gcloud.* with optional $HERMES_HOME/scripts/gcloud_projects*.json."""
    cfg: dict = {
        "enabled": False,
        "projects": [],
        "thresholds": {},
        "billing_account_ids": [],
        "billing_account_id": "",
    }
    try:
        from ops_config import load_config

        oc = load_config().get("gcloud") or {}
        if isinstance(oc, dict):
            cfg.update({k: v for k, v in oc.items() if v is not None})
    except Exception:
        pass

    scripts = HERMES_HOME / "scripts"
    file_cfg: dict = {}
    for name in ("gcloud_projects.json", "gcloud_projects.example.json"):
        file_cfg = _read_json_file(scripts / name)
        if file_cfg.get("projects"):
            break

    # ops-config projects win when non-empty; else file
    if not cfg.get("projects") and file_cfg.get("projects"):
        cfg["projects"] = file_cfg["projects"]
    if not cfg.get("thresholds") and file_cfg.get("thresholds"):
        cfg["thresholds"] = file_cfg["thresholds"]
    if not cfg.get("billing_account_ids") and file_cfg.get("billing_account_ids"):
        cfg["billing_account_ids"] = file_cfg["billing_account_ids"]
    if not cfg.get("billing_account_id") and file_cfg.get("billing_account_id"):
        cfg["billing_account_id"] = file_cfg["billing_account_id"]

    # File-only installs imply enabled when projects exist
    if cfg.get("projects") and not isinstance(cfg.get("enabled"), bool):
        cfg["enabled"] = True
    return cfg


def activate_sa_if_configured() -> str | None:
    """Point gcloud at Hermes SA key if present. Returns status note."""
    key = (
        os.environ.get("HERMES_GCLOUD_SA_KEY")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        or ""
    ).strip()
    if not key:
        default = HERMES_HOME / "secrets" / "gcloud-ops.json"
        if default.is_file():
            key = str(default)
    if not key:
        return None
    key_path = Path(key)
    if not key_path.is_file():
        return f"SA key missing: {key}"
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(key_path)
    r = subprocess.run(
        [
            GCLOUD,
            "auth",
            "activate-service-account",
            f"--key-file={key_path}",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )
    if r.returncode != 0:
        return f"activate-service-account failed: {(r.stderr or r.stdout or '')[-300:]}"
    return f"SA active via {key_path.name}"


def gcloud_json(args: list[str], timeout: int = 90) -> tuple[object | None, str]:
    r = subprocess.run(
        [GCLOUD, *args, "--format=json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "gcloud failed").strip()
        return None, err[-400:]
    raw = (r.stdout or "").strip()
    if not raw:
        return None, "empty"
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError:
        return None, "invalid json"


def gcloud_text(args: list[str], timeout: int = 90) -> tuple[str, int]:
    r = subprocess.run(
        [GCLOUD, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return out[-2000:], r.returncode


def scan_cloud_run(project: str, region: str, watch: list[str], thresholds: dict) -> list[str]:
    issues: list[str] = []
    notes: list[str] = []
    data, err = gcloud_json(
        ["run", "services", "list", f"--project={project}", f"--region={region}"]
    )
    if data is None:
        if "SERVICE_DISABLED" in err or "has not been used" in err.lower():
            return ["note: Cloud Run API disabled in this project"]
        issues.append(f"Cloud Run list failed: {err}")
        return issues

    services = data if isinstance(data, list) else []
    notes.append(f"Cloud Run services: {len(services)}")
    by_name = {}
    for svc in services:
        meta = svc.get("metadata") or {}
        name = meta.get("name") or ""
        by_name[name] = svc

    targets = watch or list(by_name.keys())[:8]
    for name in targets:
        svc = by_name.get(name)
        if not svc:
            if watch:
                issues.append(f"Cloud Run missing watched service `{name}`")
            continue
        status = svc.get("status") or {}
        url = status.get("url") or ""
        conds = status.get("conditions") or []
        ready = next((c for c in conds if c.get("type") == "Ready"), None)
        if ready and ready.get("status") != "True":
            issues.append(
                f"Cloud Run `{name}` not Ready: {ready.get('message') or ready.get('status')}"
            )
        else:
            notes.append(f"Cloud Run `{name}` Ready url={url}")

        if os.environ.get("HERMES_GCLOUD_LOG_SCAN", "").strip() in {"1", "true", "yes"}:
            filt = (
                f'resource.type="cloud_run_revision" '
                f'resource.labels.service_name="{name}" '
                f'severity>=ERROR'
            )
            logs, code = gcloud_text(
                [
                    "logging",
                    "read",
                    filt,
                    f"--project={project}",
                    "--freshness=1h",
                    "--limit=30",
                    "--format=value(timestamp)",
                ],
                timeout=60,
            )
            if code == 0:
                count = len([ln for ln in logs.splitlines() if ln.strip()])
                thr = float(thresholds.get("cloud_run_error_logs_1h", 25))
                if count >= thr:
                    issues.append(
                        f"Cloud Run `{name}` error logs last 1h: {count} (>= {thr:g})"
                    )
                else:
                    notes.append(f"Cloud Run `{name}` error logs 1h: {count}")

    return issues + [f"note: {n}" for n in notes]


def scan_functions(project: str, region: str) -> list[str]:
    data, err = gcloud_json(
        ["functions", "list", f"--project={project}", f"--gen2", f"--region={region}"]
    )
    if data is None:
        data, err = gcloud_json(["functions", "list", f"--project={project}"])
    if data is None:
        return [f"note: Functions list skipped: {err}"]
    items = data if isinstance(data, list) else []
    out = [f"note: Cloud Functions: {len(items)}"]
    for fn in items[:25]:
        name = (fn.get("name") or "").split("/")[-1] or str(fn.get("name"))
        state = str(fn.get("state") or fn.get("status") or "")
        if any(x in state.upper() for x in ("FAILED", "OFFLINE", "UNKNOWN")):
            out.append(f"Function `{name}` state={state}")
    return out


def scan_billing(billing_accounts: list[str], thresholds: dict) -> list[str]:
    accounts = [a.strip() for a in billing_accounts if a and str(a).strip()]
    if not accounts:
        return [
            "note: billing_account_id(s) unset — skip cost scan "
            "(set in ops-config gcloud.* or gcloud_projects.json)"
        ]
    out: list[str] = []
    warn = float(thresholds.get("daily_cost_usd_warn") or 50)
    for billing_account in accounts:
        data, err = gcloud_json(
            ["billing", "budgets", "list", f"--billing-account={billing_account}"]
        )
        if data is None:
            out.append(f"note: billing {billing_account} budgets unavailable: {err[-160:]}")
            continue
        items = data if isinstance(data, list) else []
        out.append(f"note: billing {billing_account}: {len(items)} budget(s) (warn ${warn:g}/day)")
        for b in items[:8]:
            name = (b.get("displayName") or b.get("name") or "budget")[-80:]
            out.append(f"note: budget `{name}`")
    return out


try:
    from weekend_policy import telegram_hitl_allowed  # noqa: E402
except Exception:  # pragma: no cover

    def telegram_hitl_allowed(when=None):
        return True


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cfg = load_gcloud_config()
    if not cfg.get("enabled", False) and not (cfg.get("projects") or []):
        print("gcloud ops scan disabled (set gcloud.enabled + projects in ops-config)")
        print(json.dumps({"wakeAgent": False}))
        return 0

    projects = [p for p in cfg.get("projects") or [] if p.get("enabled", True)]
    thresholds = cfg.get("thresholds") or {}
    billing_ids = list(cfg.get("billing_account_ids") or [])
    if cfg.get("billing_account_id"):
        billing_ids.insert(0, str(cfg.get("billing_account_id")))
    seen_b: set[str] = set()
    billing_ids = [b for b in billing_ids if not (b in seen_b or seen_b.add(b))]

    sa_note = activate_sa_if_configured()
    lines = [
        f"Updated: {stamp}",
        f"Auth: {sa_note or 'ambient gcloud user (no HERMES_GCLOUD_SA_KEY)'}",
        "",
    ]
    issues: list[str] = []

    ver, code = gcloud_text(["version", "--format=value(google-cloud-sdk)"])
    if code != 0:
        print("gcloud CLI not available")
        print(json.dumps({"wakeAgent": False}))
        return 1

    if not projects:
        lines.append("No projects configured (ops-config gcloud.projects or gcloud_projects.json)")
        issues.append("No GCP projects configured for Hermes ops scan")

    for proj in projects:
        pid = proj.get("id") or ""
        label = proj.get("label") or pid
        region = proj.get("region") or "us-central1"
        watch = proj.get("watch_run_services") or []
        lines.append(f"### {label} (`{pid}`)")
        if not pid:
            lines.append("- invalid project entry")
            continue

        run_lines = scan_cloud_run(pid, region, watch, thresholds)
        fn_lines = scan_functions(pid, region)
        for ln in run_lines + fn_lines:
            if ln.startswith("note: "):
                lines.append(f"- {ln[6:]}")
            else:
                lines.append(f"- ISSUE: {ln}")
                issues.append(f"{label}: {ln}")
        lines.append("")

    bill_lines = scan_billing(billing_ids, thresholds)
    lines.append("### Billing")
    for ln in bill_lines:
        if ln.startswith("note: "):
            lines.append(f"- {ln[6:]}")
        else:
            lines.append(f"- ISSUE: {ln}")
            issues.append(ln)
    lines.append("")

    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    _atomic_write(pipe, replace_section(existing, "GCP ops scan", "\n".join(lines)))

    costs = BRAIN_DIR / "COSTS.md"
    cost_section = (
        f"Updated: {stamp}\n\n"
        + ("\n".join(f"- {i}" for i in issues[:20]) if issues else "- No threshold issues.")
        + "\n\nSee PIPELINES → GCP ops scan for service detail.\n"
    )
    cur = costs.read_text(encoding="utf-8") if costs.exists() else "# COSTS\n\n"
    if not cur.lstrip().startswith("#"):
        cur = "# COSTS\n\n" + cur
    _atomic_write(costs, replace_section(cur, "GCP ops", cost_section))

    wake = bool(issues)
    notify_ok = telegram_hitl_allowed()
    if wake and notify_ok:
        print("GCP ops scan: issues found")
        for i in issues[:15]:
            print(f"  ! {i}")
        print("NEW_FAILURES=1")
        print(json.dumps({"wakeAgent": False, "needsHuman": True, "issueCount": len(issues)}))
        status = (
            "blocked"
            if any("failed" in i.lower() or "not ready" in i.lower() for i in issues)
            else "ok"
        )
        summary = f"GCP ops: {len(issues)} issue(s); see PIPELINES (no autofix wake)"
    elif wake and not notify_ok:
        status = "ok"
        summary = f"GCP ops: {len(issues)} issue(s); Telegram suppressed (outside notify window)"
    else:
        status = "silent"
        summary = "GCP ops scan clean"

    try:
        from ops_audit import append_event

        append_event(
            job_id=JOB_ID,
            name="GCP ops scan",
            status=status if wake else "silent",
            summary=summary,
            detail="\n".join(issues[:12]),
            artifacts=[str(pipe), str(costs)],
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)

    return 1 if wake else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired:
        print("gcloud ops scan timed out", file=sys.stderr)
        print(json.dumps({"wakeAgent": False}))
        raise SystemExit(1)
