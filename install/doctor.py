#!/usr/bin/env python3
"""Sanity-check a hermes-ops-kit install."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def hermes_home() -> Path:
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from hermes_paths import hermes_home as _home

    return _home()


def ok(msg: str) -> None:
    print(f"OK   {msg}")


def warn(msg: str) -> None:
    print(f"WARN {msg}")


def bad(msg: str) -> None:
    print(f"FAIL {msg}")


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def main() -> int:
    failures = 0
    home = hermes_home()
    print(f"HERMES_HOME={home}")

    if have("hermes"):
        ok("hermes CLI on PATH")
        r = subprocess.run(
            ["hermes", "cron", "status"], capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0 and "running" in (r.stdout or "").lower():
            ok("hermes gateway / cron ticker appears running")
        else:
            warn("hermes cron status did not report a healthy gateway")
            print((r.stdout or r.stderr or "")[:400])
    else:
        bad("hermes CLI not found — install Hermes Agent first")
        failures += 1

    if have("gh"):
        ok("gh CLI on PATH")
        r = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            ok("gh authenticated")
        else:
            warn("gh not authenticated (or HERMES_GH_TOKEN not visible to this shell)")
    else:
        bad("gh CLI not found")
        failures += 1

    if os.environ.get("HERMES_GH_TOKEN"):
        ok("HERMES_GH_TOKEN is set")
    else:
        warn("HERMES_GH_TOKEN not set — ambient gh login will be used")

    scripts = home / "scripts"
    for req in (
        "ops_config.py",
        "ops_audit.py",
        "pipeline-scan.py",
        "server.py",
        "roadmap_cli.py",
    ):
        if (scripts / req).is_file():
            ok(f"script {req}")
        else:
            bad(f"missing script {req} — run install/install.py")
            failures += 1

    cfg = None
    for name in ("ops-config.yaml", "ops-config.yml", "ops-config.json"):
        p = home / name
        if p.is_file():
            ok(f"config {p}")
            cfg = p
            break
        p2 = Path.home() / ".hermes" / name
        if p2.is_file():
            ok(f"config {p2}")
            cfg = p2
            break
    if not cfg:
        bad("no ops-config.yaml|json found in HERMES_HOME or ~/.hermes")
        failures += 1

    brain = home / "brain"
    if (brain / "PRODUCTS.md").is_file():
        ok("brain PRODUCTS.md present")
    else:
        warn("brain not seeded — re-run install.py")

    roadmaps = Path.home() / ".hermes" / "roadmaps.json"
    if roadmaps.is_file():
        ok(f"roadmaps {roadmaps}")
    else:
        warn("missing ~/.hermes/roadmaps.json")

    port = 8888
    if cfg and cfg.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            port = int(data.get("ui_port") or 8888)
        except Exception:
            pass
    elif cfg and cfg.suffix.lower() == ".json":
        try:
            port = int(json.loads(cfg.read_text(encoding="utf-8")).get("ui_port") or 8888)
        except Exception:
            pass

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            ok(f"roadmap UI listening on :{port}")
    except OSError:
        warn(f"roadmap UI not listening on :{port} (start server.py or wait for watchdog)")

    generated = home / "cron" / "generated" / "CREATE_JOBS.md"
    if generated.is_file():
        ok(f"job create guide {generated}")
    else:
        warn("no generated CREATE_JOBS.md — run install.py without --skip-jobs")

    print()
    if failures:
        print(f"{failures} failure(s)")
        return 1
    print("doctor finished with no hard failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
