#!/usr/bin/env python3
"""Load hermes-ops-kit configuration (YAML or JSON).

Search order:
  1. HERMES_OPS_CONFIG (file path)
  2. $HERMES_HOME/ops-config.yaml|json
  3. ~/.hermes/ops-config.yaml|json
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "timezone": "America/Chicago",
    "ui_port": 8888,
    "notify_window": {
        "weekdays": [0, 1, 2, 3, 4],
        "start": "09:00",
        "end": "17:00",
        "always_allow_jobs": ["f6ops2100"],
    },
    "projects_root": "",
    "github": {
        "org": "your-org",
        "repos": [
            {
                "name": "example-app",
                "slug": "your-org/example-app",
                "critical_workflows": ["CI"],
            },
        ],
    },
    "products": ["example-app"],
    "projects": {
        "example-app": {
            "path": "example-app",
            "checks": [["Compile check", ["echo", "configure me"]]],
        }
    },
    # Empty on purpose: agent jobs inherit Hermes' current model unless
    # ops-config.yaml sets models.default and/or per-part overrides.
    "models": {},
    # Optional advanced topology flags (jobs still present in template;
    # disable unused ones in the live cron registry after render).
    "features": {
        "night_executor": True,  # d4execnight
        "ui_live": True,  # h11uilive23 — needs ui-live-scan.py
        "gcloud_ops": False,  # h12gcloud0730 — needs SA + gcloud-ops-scan.py
        "checkin_ui": True,  # /checkin human ritual page
    },
    "tracked_branches": ["main", "trunk", "dev", "qa"],
    "gcloud": {
        "enabled": False,
        "projects": [],
        "thresholds": {},
        "billing_account_ids": [],
        "billing_account_id": "",
    },
    "ui_live": {
        "enabled": False,
        "local_checks": [],
    },
}


def _hermes_home() -> Path:
    from hermes_paths import hermes_home

    return hermes_home()


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("HERMES_OPS_CONFIG", "").strip()
    if env:
        paths.append(Path(env))
    home = _hermes_home()
    paths.extend(
        [
            home / "ops-config.yaml",
            home / "ops-config.yml",
            home / "ops-config.json",
            Path.home() / ".hermes" / "ops-config.yaml",
            Path.home() / ".hermes" / "ops-config.yml",
            Path.home() / ".hermes" / "ops-config.json",
        ]
    )
    return paths


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "PyYAML is required for ops-config.yaml. "
            "Install with: pip install pyyaml  (or use ops-config.json)"
        ) from exc
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULTS))
    for path in _candidate_paths():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        try:
            if path.suffix.lower() in {".yaml", ".yml"}:
                data = _load_yaml(text)
            else:
                data = json.loads(text)
        except SystemExit:
            # PyYAML missing — try next candidate (ops-config.json)
            continue
        cfg = _deep_merge(cfg, data)
        cfg["_config_path"] = str(path)
        break
    pr = os.environ.get("HERMES_PROJECTS_ROOT", "").strip()
    if pr:
        cfg["projects_root"] = pr
    elif not cfg.get("projects_root"):
        cfg["projects_root"] = str(Path.home())
    tz = os.environ.get("HERMES_OPS_TIMEZONE", "").strip()
    if tz:
        cfg["timezone"] = tz
    return cfg


def github_org(cfg: dict[str, Any] | None = None) -> str:
    c = cfg or load_config()
    return str((c.get("github") or {}).get("org") or "your-org")


def repo_slugs(cfg: dict[str, Any] | None = None) -> list[str]:
    c = cfg or load_config()
    repos = (c.get("github") or {}).get("repos") or []
    out: list[str] = []
    for r in repos:
        if isinstance(r, str):
            out.append(r if "/" in r else f"{github_org(c)}/{r}")
        elif isinstance(r, dict):
            slug = r.get("slug") or f"{github_org(c)}/{r.get('name')}"
            out.append(str(slug))
    return out


def repo_name_map(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    c = cfg or load_config()
    org = github_org(c)
    result: dict[str, str] = {}
    for r in (c.get("github") or {}).get("repos") or []:
        if isinstance(r, str):
            name = r.split("/")[-1]
            result[name] = r if "/" in r else f"{org}/{r}"
        elif isinstance(r, dict):
            name = str(r.get("name") or r.get("slug", "").split("/")[-1])
            slug = str(r.get("slug") or f"{org}/{name}")
            result[name] = slug
    for p in c.get("products") or []:
        result.setdefault(str(p), f"{org}/{p}")
    return result


def critical_workflows(cfg: dict[str, Any] | None = None) -> dict[str, list[str]]:
    c = cfg or load_config()
    out: dict[str, list[str]] = {}
    for r in (c.get("github") or {}).get("repos") or []:
        if not isinstance(r, dict):
            continue
        slug = str(r.get("slug") or f"{github_org(c)}/{r.get('name')}")
        wfs = r.get("critical_workflows") or ["CI"]
        out[slug] = list(wfs)
    return out


def product_names(cfg: dict[str, Any] | None = None) -> list[str]:
    c = cfg or load_config()
    products = list(c.get("products") or [])
    if products:
        return [str(p) for p in products]
    return list(repo_name_map(c).keys())


def timezone_name(cfg: dict[str, Any] | None = None) -> str:
    return str((cfg or load_config()).get("timezone") or "America/Chicago")


def notify_window(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict((cfg or load_config()).get("notify_window") or {})


def projects_root(cfg: dict[str, Any] | None = None) -> Path:
    c = cfg or load_config()
    return Path(str(c.get("projects_root") or Path.home()))


def sentinel_projects(cfg: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    c = cfg or load_config()
    root = projects_root(c)
    raw = c.get("projects") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        rel = spec.get("path") or name
        checks_in = spec.get("checks") or []
        checks: list[tuple[str, list[str]]] = []
        for item in checks_in:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                checks.append((str(item[0]), list(item[1])))
            elif isinstance(item, dict):
                checks.append(
                    (str(item.get("label") or "check"), list(item.get("cmd") or []))
                )
        out[str(name)] = {"path": root / str(rel), "checks": checks}
    return out


def gcloud_settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    c = cfg or load_config()
    raw = c.get("gcloud") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def ui_live_settings(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    c = cfg or load_config()
    raw = c.get("ui_live") or {}
    return dict(raw) if isinstance(raw, dict) else {}


AGENT_MODEL_ROLES = (
    "pm",
    "market",
    "ops_review",
    "autofix",
    "executor",
    "executor_night",
    "ui_live",
)

JOB_MODEL_ROLES = {
    "026c0a4c82b7": "autofix",
    "c3pm0930": "pm",
    "d4exec1014": "executor",
    "d4execnight": "executor_night",
    "e5market184": "market",
    "f6ops2100": "ops_review",
    "h11uilive23": "ui_live",
}


def _provider_model(block: Any) -> tuple[str, str]:
    if not isinstance(block, dict):
        return "", ""
    return str(block.get("provider") or "").strip(), str(block.get("model") or "").strip()


def resolve_model(cfg: dict[str, Any] | None, role: str) -> dict[str, str]:
    """Resolve provider/model for one agent part.

    Omitted parts inherit ``models.default``. Omitted ``models`` entirely
    leaves provider/model empty so Hermes uses its current default.
    Optional ``fallback: {provider, model}`` on the part or on default.
    """
    c = cfg or load_config()
    models = c.get("models") or {}
    if not isinstance(models, dict):
        models = {}
    default = models.get("default") if isinstance(models.get("default"), dict) else {}
    part = models.get(role) if role != "default" and isinstance(models.get(role), dict) else {}

    d_provider, d_model = _provider_model(default)
    p_provider, p_model = _provider_model(part)
    provider = p_provider or d_provider
    model = p_model or d_model

    fallback_block: Any = None
    if part.get("fallback"):
        fallback_block = part.get("fallback")
    elif default.get("fallback"):
        fallback_block = default.get("fallback")
    f_provider, f_model = _provider_model(fallback_block)

    if f_provider and f_model:
        fallback_line = (
            f"Fallback (in-flight slice only): {f_provider} / {f_model}. "
            "Never start a new item under a fallback."
        )
    else:
        fallback_line = (
            "No fallback configured — stop on 429/quota/auth. "
            "Do not invent another provider."
        )

    return {
        "provider": provider,
        "model": model,
        "fallback_provider": f_provider,
        "fallback_model": f_model,
        "fallback_line": fallback_line,
    }
