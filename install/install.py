#!/usr/bin/env python3
"""Install hermes-ops-kit into HERMES_HOME and ~/.hermes (does not overwrite live jobs.json)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

KIT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_ROOT / "install"))
sys.path.insert(0, str(KIT_ROOT / "scripts"))

from render_jobs import (  # noqa: E402
    _load_yaml_or_json,
    hermes_home,
    render,
)


def dot_hermes() -> Path:
    return Path.home() / ".hermes"


def copy_tree(src: Path, dest: Path) -> int:
    count = 0
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        if "__pycache__" in f.parts or f.suffix == ".pyc":
            continue
        out = dest / f.relative_to(src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
        count += 1
    return count


def seed_brain(home: Path, force: bool) -> None:
    brain = home / "brain"
    tmpl = KIT_ROOT / "templates" / "brain"
    brain.mkdir(parents=True, exist_ok=True)
    for f in tmpl.iterdir():
        dest = brain / f.name
        if dest.exists() and not force:
            continue
        shutil.copy2(f, dest)
        print(f"seeded brain/{f.name}")


def seed_roadmaps(force: bool) -> None:
    dest = dot_hermes() / "roadmaps.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"keep existing {dest}")
        return
    shutil.copy2(KIT_ROOT / "templates" / "roadmaps.json", dest)
    print(f"wrote {dest}")


def install_docs() -> None:
    d = dot_hermes()
    d.mkdir(parents=True, exist_ok=True)
    for name in (
        "OPS_DESIGN.md",
        "OPS_MODELS.md",
        "GITHUB_SERVICE_ACCOUNT.md",
        "ARCHITECTURE.md",
    ):
        src = KIT_ROOT / "docs" / name
        if src.is_file():
            shutil.copy2(src, d / name)
            print(f"wrote {d / name}")


def install_config(cfg_path: Path, home: Path) -> Path:
    dest = home / ("ops-config" + cfg_path.suffix)
    shutil.copy2(cfg_path, dest)
    # also mirror to ~/.hermes
    shutil.copy2(cfg_path, dot_hermes() / dest.name)
    print(f"wrote {dest}")
    print(f"wrote {dot_hermes() / dest.name}")
    return dest


def write_import_helper(rendered: dict[str, Any], home: Path) -> Path:
    """Write rendered jobs + a shell/ps1 helper that prints create guidance."""
    out_dir = home / "cron" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = out_dir / "jobs.rendered.json"
    jobs_path.write_text(
        json.dumps(rendered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for job in rendered.get("jobs") or []:
        prompt = job.get("prompt")
        if prompt:
            (out_dir / f"{job['id']}.prompt.txt").write_text(prompt, encoding="utf-8")

    guide = out_dir / "CREATE_JOBS.md"
    lines = [
        "# Create cron jobs",
        "",
        "Hermes does not silently overwrite your live `cron/jobs.json`.",
        "Use these commands (or Hermes UI) after reviewing prompts in this folder.",
        "",
        f"Rendered registry: `{jobs_path}`",
        "",
    ]
    for job in rendered.get("jobs") or []:
        sched = (job.get("schedule") or {}).get("expr", "")
        lines.append(f"## {job['id']} — {job['name']}")
        lines.append(f"- schedule: `{sched}`")
        lines.append(f"- deliver: `{job.get('deliver')}`")
        lines.append(f"- no_agent: `{job.get('no_agent')}`")
        if job.get("script"):
            lines.append(f"- script: `{job['script']}`")
        if job.get("model"):
            lines.append(f"- model: `{job.get('provider')}` / `{job.get('model')}`")
        if job.get("skills"):
            lines.append(f"- skills: {', '.join(job['skills'])}")
        if job.get("prompt"):
            lines.append(f"- prompt file: `{job['id']}.prompt.txt`")
            lines.append(
                "```bash\n"
                f"hermes cron create --name {json.dumps(job['name'])} "
                f"--schedule {json.dumps(sched)} --deliver {job.get('deliver')} "
                + (
                    f"--script {job['script']} --no-agent "
                    if job.get("no_agent") and job.get("script")
                    else ""
                )
                + (
                    f"--script {job['script']} "
                    if job.get("script") and not job.get("no_agent")
                    else ""
                )
                + " ".join(f"--skill {s}" for s in (job.get("skills") or []))
                + f" --prompt \"$(cat {out_dir.as_posix()}/{job['id']}.prompt.txt)\"\n"
                "```"
                if job.get("prompt")
                else ""
            )
        elif job.get("no_agent"):
            lines.append(
                "```bash\n"
                f"hermes cron create --name {json.dumps(job['name'])} "
                f"--schedule {json.dumps(sched)} --deliver {job.get('deliver')} "
                f"--script {job['script']} --no-agent\n"
                "```"
            )
        lines.append("")
    guide.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {jobs_path}")
    print(f"wrote {guide}")
    return guide


def main() -> int:
    ap = argparse.ArgumentParser(description="Install hermes-ops-kit")
    ap.add_argument("--config", required=True, help="Path to ops-config.yaml|json")
    ap.add_argument(
        "--force-brain",
        action="store_true",
        help="Overwrite existing empty-ish brain starter files",
    )
    ap.add_argument(
        "--force-roadmaps",
        action="store_true",
        help="Overwrite ~/.hermes/roadmaps.json",
    )
    ap.add_argument(
        "--skip-jobs",
        action="store_true",
        help="Do not render job templates",
    )
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    if not cfg_path.is_file():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 1

    cfg = _load_yaml_or_json(cfg_path)
    home = hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "scripts").mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(parents=True, exist_ok=True)
    (home / "brain").mkdir(parents=True, exist_ok=True)
    (home / "cron").mkdir(parents=True, exist_ok=True)

    n = copy_tree(KIT_ROOT / "scripts", home / "scripts")
    print(f"copied {n} script files → {home / 'scripts'}")
    n = copy_tree(KIT_ROOT / "skills", home / "skills")
    print(f"copied {n} skill files → {home / 'skills'}")

    # also mirror scripts into ~/.hermes/scripts for interactive use
    n = copy_tree(KIT_ROOT / "scripts", dot_hermes() / "scripts")
    print(f"copied {n} script files → {dot_hermes() / 'scripts'}")

    install_config(cfg_path, home)
    seed_brain(home, force=args.force_brain)
    seed_roadmaps(force=args.force_roadmaps)
    install_docs()

    os.environ["HERMES_OPS_CONFIG"] = str(home / ("ops-config" + cfg_path.suffix))
    if cfg.get("projects_root"):
        os.environ.setdefault("HERMES_PROJECTS_ROOT", str(cfg["projects_root"]))

    if not args.skip_jobs:
        rendered = render(cfg)
        guide = write_import_helper(rendered, home)
        print()
        print("Next: review and create cron jobs using")
        print(f"  {guide}")
        print("Then: python install/doctor.py")

    print()
    print("Install complete.")
    print(f"  HERMES_HOME={home}")
    print(f"  DOT_HERMES={dot_hermes()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
