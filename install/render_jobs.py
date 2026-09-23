#!/usr/bin/env python3
"""Expand templates/cron/jobs.template.json using ops-config values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

KIT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_ROOT / "scripts"))


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SystemExit("pip install pyyaml  (or pass a .json config)") from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("config root must be a mapping")
    return data


def hermes_home() -> Path:
    from hermes_paths import hermes_home as _home

    return _home()


def placeholders(cfg: dict[str, Any]) -> dict[str, str]:
    from hermes_paths import dot_hermes
    from ops_config import AGENT_MODEL_ROLES, resolve_model

    home = hermes_home()
    home_posix = home.as_posix()
    projects_root = Path(
        cfg.get("projects_root") or os.environ.get("HERMES_PROJECTS_ROOT") or Path.home()
    )
    mapping: dict[str, str] = {
        "{{HERMES_HOME}}": str(home),
        "{{HERMES_HOME_POSIX}}": home_posix,
        "{{DOT_HERMES}}": str(dot_hermes()),
        "{{DOT_HERMES_POSIX}}": dot_hermes().as_posix(),
        "{{GITHUB_ORG}}": str((cfg.get("github") or {}).get("org") or "your-org"),
        "{{HERMES_PROJECTS_ROOT}}": str(projects_root),
        "{{HERMES_PROJECTS_ROOT_POSIX}}": projects_root.as_posix(),
    }
    role_token = {
        "pm": "PM",
        "market": "MARKET",
        "ops_review": "OPS_REVIEW",
        "autofix": "AUTOFIX",
        "executor": "EXECUTOR",
        "executor_night": "EXECUTOR_NIGHT",
        "ui_live": "UI_LIVE",
    }
    for role in AGENT_MODEL_ROLES:
        resolved = resolve_model(cfg, role)
        token = role_token[role]

        def ph(name: str) -> str:
            return "{{" + name + "}}"

        mapping[ph(f"MODEL_{token}")] = resolved["model"]
        mapping[ph(f"PROVIDER_{token}")] = resolved["provider"]
        mapping[ph(f"{token}_FALLBACK_LINE")] = resolved["fallback_line"]
        mapping[ph(f"MODEL_{token}_FALLBACK")] = resolved["fallback_model"]
        mapping[ph(f"PROVIDER_{token}_FALLBACK")] = resolved["fallback_provider"]
    return mapping


def render_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for k, v in mapping.items():
            out = out.replace(k, v)
        return out
    if isinstance(value, list):
        return [render_value(x, mapping) for x in value]
    if isinstance(value, dict):
        return {k: render_value(v, mapping) for k, v in value.items()}
    return value


def load_template() -> dict[str, Any]:
    path = KIT_ROOT / "templates" / "cron" / "jobs.template.json"
    return json.loads(path.read_text(encoding="utf-8"))


def apply_job_models(rendered: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Pin or clear model/provider/fallback_providers from optional config."""
    from ops_config import JOB_MODEL_ROLES, resolve_model

    jobs = rendered.get("jobs") or []
    for job in jobs:
        if not isinstance(job, dict) or job.get("no_agent"):
            continue
        role = JOB_MODEL_ROLES.get(str(job.get("id") or ""))
        if not role:
            continue
        resolved = resolve_model(cfg, role)
        if resolved["provider"] and resolved["model"]:
            job["model"] = resolved["model"]
            job["provider"] = resolved["provider"]
        else:
            job.pop("model", None)
            job.pop("provider", None)
        if resolved["fallback_provider"] and resolved["fallback_model"]:
            job["fallback_providers"] = [
                {
                    "provider": resolved["fallback_provider"],
                    "model": resolved["fallback_model"],
                }
            ]
        elif "fallback_providers" in job:
            job["fallback_providers"] = []
    return rendered


def render(cfg: dict[str, Any]) -> dict[str, Any]:
    mapping = placeholders(cfg)
    rendered = render_value(load_template(), mapping)
    return apply_job_models(rendered, cfg)


def print_create_commands(rendered: dict[str, Any], scripts_dir: Path) -> None:
    print("# Generated hermes cron create commands")
    print("# Review before running. Does not overwrite an existing jobs.json.\n")
    for job in rendered.get("jobs") or []:
        jid = job["id"]
        name = job["name"]
        sched = (job.get("schedule") or {}).get("expr") or ""
        deliver = job.get("deliver") or "local"
        parts = [
            "hermes cron create",
            f"--name {json.dumps(name)}",
            f"--schedule {json.dumps(sched)}",
            f"--deliver {deliver}",
        ]
        if job.get("no_agent"):
            parts.append("--no-agent")
        script = job.get("script")
        if script:
            parts.append(f"--script {json.dumps(script)}")
        for sk in job.get("skills") or []:
            parts.append(f"--skill {json.dumps(sk)}")
        model = job.get("model")
        provider = job.get("provider")
        # hermes create may accept model via other flags; include in prompt header note
        prompt = job.get("prompt")
        if prompt:
            prompt_path = scripts_dir.parent / "cron" / "generated" / f"{jid}.prompt.txt"
            parts.append(f"--prompt-file {json.dumps(str(prompt_path))}")
            print(f"# model={model} provider={provider}")
        print(" ".join(parts))
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Render hermes-ops-kit cron job templates")
    ap.add_argument("--config", required=True, help="Path to ops-config.yaml|json")
    ap.add_argument(
        "--out",
        default="",
        help="Write rendered JSON to this path (default: stdout summary + create cmds)",
    )
    ap.add_argument(
        "--write-prompts",
        action="store_true",
        help="Write per-job prompt files under $HERMES_HOME/cron/generated/",
    )
    ap.add_argument(
        "--print-create",
        action="store_true",
        help="Print hermes cron create command sketches",
    )
    args = ap.parse_args()

    cfg = _load_yaml_or_json(Path(args.config))
    rendered = render(cfg)
    home = hermes_home()

    if args.write_prompts:
        out_dir = home / "cron" / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        for job in rendered.get("jobs") or []:
            prompt = job.get("prompt")
            if not prompt:
                continue
            path = out_dir / f"{job['id']}.prompt.txt"
            path.write_text(prompt, encoding="utf-8")
            print(f"wrote {path}", file=sys.stderr)

    if args.out:
        Path(args.out).write_text(
            json.dumps(rendered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.out}", file=sys.stderr)
    elif not args.print_create:
        json.dump(rendered, sys.stdout, indent=2, ensure_ascii=False)
        print()

    if args.print_create:
        print_create_commands(rendered, home / "scripts")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
