#!/usr/bin/env python3
"""Project Sentinel — daily local health-check digest for all user projects.

Tool resolution (avoid false FAIL when cron PATH is thin):
  - ruff: <repo>/.venv (or venv) Scripts/bin, else PATH
  - tsc/eslint: node + <repo>/node_modules/... (not bare npx if local install exists)
  - Hermes-bundled node prepended to PATH when present
Missing verifiers → UNAVAILABLE (ops gap), not product FAIL.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(os.environ.get("HERMES_PROJECTS_ROOT", str(Path.home())))
BRAIN_DIR = Path(
    os.environ.get("HERMES_BRAIN_DIR", str(Path(__file__).resolve().parent.parent / "brain"))
)
SCRIPTS = Path(__file__).resolve().parent
# Cron shells do not consistently export HERMES_HOME. Pin audit writes.
os.environ.setdefault("HERMES_HOME", str(SCRIPTS.parent))
# Cron's minimal Windows env may omit Hermes-bundled Node.
NODE_BIN = SCRIPTS.parent / "node"
if NODE_BIN.is_dir():
    os.environ["PATH"] = str(NODE_BIN) + os.pathsep + os.environ.get("PATH", "")


def _which(name: str) -> str | None:
    return shutil.which(name)


def resolve_node() -> str | None:
    if NODE_BIN.is_dir():
        for cand in (NODE_BIN / "node.exe", NODE_BIN / "node"):
            if cand.is_file():
                return str(cand)
    return _which("node")


def resolve_ruff(repo: Path) -> list[str] | None:
    """Prefer repo venv ruff so cron without global ruff still works."""
    names = ("ruff.exe", "ruff")
    for venv in (".venv", "venv"):
        for sub in ("Scripts", "bin"):
            for name in names:
                p = repo / venv / sub / name
                if p.is_file():
                    return [str(p)]
    w = _which("ruff")
    return [w] if w else None


def resolve_js_tool(repo: Path, package: str, bin_name: str) -> list[str] | None:
    """Run local node_modules binary via node (avoids Windows .cmd shim issues)."""
    node = resolve_node()
    if not node:
        return None
    # typescript/bin/tsc, eslint/bin/eslint.js variants
    candidates = [
        repo / "node_modules" / package / "bin" / bin_name,
        repo / "node_modules" / package / "bin" / f"{bin_name}.js",
        repo / "node_modules" / ".bin" / bin_name,
    ]
    if os.name == "nt":
        candidates.append(repo / "node_modules" / ".bin" / f"{bin_name}.cmd")
    for p in candidates:
        if not p.is_file():
            continue
        if p.suffix.lower() in {".cmd", ".bat", ".ps1"}:
            # Let cmd resolve npm shim
            return ["cmd", "/c", str(p)]
        # JS entry or extensionless — drive with node when possible
        if p.suffix.lower() in {".js", ""} or "node_modules" in p.parts:
            # .bin/tsc may be a shell script; prefer package bin js
            if p.name == bin_name and (repo / "node_modules" / package / "bin").is_dir():
                pkg_bin = repo / "node_modules" / package / "bin" / bin_name
                pkg_js = repo / "node_modules" / package / "bin" / f"{bin_name}.js"
                if pkg_js.is_file():
                    return [node, str(pkg_js)]
                if pkg_bin.is_file():
                    # typescript's bin/tsc is a node script without .js
                    return [node, str(pkg_bin)]
            if p.suffix.lower() == ".js" or package in str(p):
                return [node, str(p)]
    # Last resort: npx -p <package> so version is pinned to registry package name
    npx = _which("npx")
    if npx and node:
        if os.name == "nt":
            return ["cmd", "/c", "npx", "--yes", "-p", package, bin_name]
        return ["npx", "--yes", "-p", package, bin_name]
    return None


def go_cmd() -> str | None:
    """Resolve go: PATH, then common local install (tools/go)."""
    w = _which("go")
    if w:
        return w
    env = os.environ.get("HERMES_GO") or os.environ.get("GOTOOLDIR")
    if env:
        p = Path(env)
        if p.is_file():
            return str(p)
        for name in ("go.exe", "go"):
            c = p / name
            if c.is_file():
                return str(c)
    for p in (
        BASE / "tools" / "go" / "bin" / "go.exe",
        BASE / "tools" / "go" / "bin" / "go",
        Path.home() / "go" / "bin" / "go.exe",
        Path.home() / "sdk" / "go" / "bin" / "go.exe",
        Path(r"C:\Program Files\Go\bin\go.exe"),
    ):
        if p.is_file():
            return str(p)
    return None


def ensure_java_home() -> str | None:
    """Set JAVA_HOME if a JDK is discoverable; return java binary or None."""
    existing = os.environ.get("JAVA_HOME")
    if existing and (Path(existing) / "bin" / "java.exe").is_file():
        return str(Path(existing) / "bin" / "java.exe")
    if existing and (Path(existing) / "bin" / "java").is_file():
        return str(Path(existing) / "bin" / "java")

    w = _which("java")
    candidates: list[Path] = []
    if w:
        candidates.append(Path(w))
    for p in (
        BASE / "tools" / "jdk" / "bin" / "java.exe",
        Path(r"C:\Program Files\Android\Android Studio\jbr\bin\java.exe"),
        Path(r"C:\Program Files\Eclipse Adoptium"),
        Path(r"C:\Program Files\Java"),
        Path(r"C:\Program Files\Microsoft"),
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Eclipse Adoptium")),
    ):
        if p.is_file():
            candidates.append(p)
        elif p.is_dir():
            for match in sorted(p.rglob("java.exe"))[:5]:
                candidates.append(match)

    for java in candidates:
        if not java.is_file():
            continue
        # Prefer a real JDK home (…/bin/java → parent of bin)
        home = java.parent.parent
        if (home / "bin").is_dir():
            os.environ.setdefault("JAVA_HOME", str(home))
            # Prepend so gradlew sees it
            os.environ["PATH"] = str(home / "bin") + os.pathsep + os.environ.get("PATH", "")
            return str(java)
    return None


def gradle_cmd(repo: Path) -> list[str] | None:
    if not ensure_java_home() and not _which("java"):
        return None  # honest UNAVAILABLE — gradlew only prints JAVA_HOME errors
    if os.name == "nt":
        bat = repo / "gradlew.bat"
        if bat.is_file():
            return ["cmd", "/c", str(bat)]
    sh = repo / "gradlew"
    if sh.is_file():
        return [str(sh)]
    return None


def build_checks(repo_name: str, path: Path) -> list[tuple[str, list[str] | None]]:
    """Return (description, argv|None). None = tool missing → UNAVAILABLE."""
    if repo_name == "tether":
        ruff = resolve_ruff(path)
        return [
            ("Lint issues", (ruff + ["check", ".", "--statistics"]) if ruff else None),
            ("Format drift", (ruff + ["format", "--check", "."]) if ruff else None),
        ]
    if repo_name == "ntviewer":
        tsc = resolve_js_tool(path, "typescript", "tsc")
        return [("Type errors", (tsc + ["--noEmit"]) if tsc else None)]
    if repo_name == "paladin-streaming":
        go = go_cmd()
        if not go:
            return [
                ("Go vet internal", None),
                ("Go vet cmd", None),
            ]
        return [
            ("Go vet internal", [go, "vet", "./internal/..."]),
            ("Go vet cmd", [go, "vet", "./cmd/..."]),
        ]
    if repo_name == "secure_comms":
        g = gradle_cmd(path)
        if not g:
            return [("Gradle verify", None)]
        return [("Gradle verify", g + ["verify", "--no-daemon"])]
    if repo_name == "paxdev":
        return [("AST graph generation", [sys.executable, "ast_to_graph.py", "."])]
    if repo_name == "aedif-marketplace":
        return [
            (
                "Manifest check",
                [sys.executable, str(SCRIPTS / "check-manifest.py"), str(path)],
            )
        ]
    if repo_name == "taskwork":
        return [
            (
                "Package import",
                [sys.executable, "-c", "import taskwork"],
            )
        ]
    if repo_name == "aedif-ai":
        tsc = resolve_js_tool(path, "typescript", "tsc")
        eslint = resolve_js_tool(path, "eslint", "eslint")
        return [
            ("TypeScript compile", (tsc + ["--noEmit"]) if tsc else None),
            (
                "ESLint",
                (eslint + [".", "--max-warnings=0"]) if eslint else None,
            ),
        ]
    return []


PROJECT_NAMES = [
    "tether",
    "ntviewer",
    "paladin-streaming",
    "secure_comms",
    "paxdev",
    "aedif-marketplace",
    "aedif-ai",
    "taskwork",
]


def run_cmd(cmd, cwd=None, timeout=180):
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        out = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        return result.returncode == 0, [ln for ln in out.splitlines() if ln.strip()]
    except subprocess.TimeoutExpired:
        return False, ["TIMEOUT"]
    except FileNotFoundError:
        return False, [f"Command not found: {cmd[0]}"]
    except Exception as exc:
        return False, [str(exc)]


def write_brain_health(results: list[dict], action_items: list[str]) -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## Local health (sentinel) — {stamp}",
        "",
    ]
    for row in results:
        status = row["status"]
        lines.append(f"- **{row['project']}**: {status} — {row['summary']}")
    if action_items:
        lines.append("")
        lines.append("### Action items")
        for item in action_items:
            lines.append(f"- {item}")
    lines.append("")
    block = "\n".join(lines)
    existing = pipe.read_text(encoding="utf-8") if pipe.exists() else "# PIPELINES\n\n"
    marker = "## Local health (sentinel)"
    if marker in existing:
        pre = existing.split(marker)[0].rstrip() + "\n\n"
        rest = existing.split(marker, 1)[1]
        if "\n## " in rest:
            rest = rest.split("\n## ", 1)[1]
            existing = pre + block + "## " + rest
        else:
            existing = pre + block
    else:
        existing = existing.rstrip() + "\n\n" + block
    pipe.write_text(existing, encoding="utf-8")


try:
    from weekend_policy import telegram_hitl_allowed
except Exception:  # pragma: no cover

    def telegram_hitl_allowed(when=None):
        return True


def main() -> int:
    action_items: list[str] = []
    unavailable_items: list[str] = []
    results: list[dict] = []
    fail_detail: list[str] = []

    for proj_name in PROJECT_NAMES:
        path = BASE / proj_name
        if not path.is_dir():
            action_items.append(f"{proj_name}: directory not found")
            results.append(
                {"project": proj_name, "status": "FAIL", "summary": "missing directory"}
            )
            continue

        fails: list[str] = []
        unavailable: list[str] = []
        for desc, cmd in build_checks(proj_name, path):
            if cmd is None:
                unavailable.append(desc)
                unavailable_items.append(
                    f"{proj_name}: {desc} unavailable (tool not in repo venv/node_modules or PATH)"
                )
                continue
            timeout = 300 if "gradle" in desc.lower() else 180
            ok, lines = run_cmd(cmd, cwd=path, timeout=timeout)
            if not ok:
                text = "\n".join(lines).lower()
                if (
                    "command not found:" in text
                    or "java_home is not set" in text
                    or "no 'java' command" in text
                    or "unable to locate a java runtime" in text
                    or "is not recognized as an internal" in text
                    or "executable file not found" in text
                ):
                    unavailable.append(desc)
                    unavailable_items.append(
                        f"{proj_name}: {desc} unavailable (cron toolchain)"
                    )
                    continue
                fails.append(desc)
                action_items.append(f"{proj_name}: {desc} failed")
                for ln in lines[-3:]:
                    fail_detail.append(f"{proj_name}/{desc}: {ln}")

        if fails:
            status = "FAIL"
            summary = "; ".join(fails)
        elif unavailable:
            status = "UNAVAILABLE"
            summary = "; ".join(unavailable) + " (tooling missing)"
        else:
            status = "OK"
            summary = "all checks passed"
        results.append({"project": proj_name, "status": status, "summary": summary})

    present = sum(1 for n in PROJECT_NAMES if (BASE / n).is_dir())
    try:
        write_brain_health(results, action_items)
    except Exception as exc:
        print(f"Brain write skipped: {exc}", file=sys.stderr)

    try:
        from ops_audit import append_event

        # Audit status is health outcome; cron exit must stay 0 when the script
        # itself succeeded (no_agent treats non-zero as "script failed").
        append_event(
            job_id="41cb7755ae6d",
            name="Project Sentinel",
            status="error"
            if action_items
            else ("partial" if unavailable_items else "ok"),
            summary=(
                f"Health check {present}/{len(PROJECT_NAMES)} present; "
                f"{len(action_items)} product action item(s); "
                f"{len(unavailable_items)} unavailable verifier(s)"
            ),
            detail="\n".join((action_items + unavailable_items)[:12]),
            artifacts=[str(BRAIN_DIR / "PIPELINES.md")],
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)

    # no_agent delivery:
    # - exit 0 + empty stdout → silent success
    # - exit 0 + stdout → deliver digest (HITL window only)
    # - exit != 0 → cron marks job ERROR ("script failed") even if health ran
    if not action_items and not unavailable_items:
        return 0

    if not telegram_hitl_allowed():
        # Brain/PIPELINES already updated; stay quiet outside HITL.
        return 0

    print("PROJECT SENTINEL — health notes")
    print(f"Projects present: {present}/{len(PROJECT_NAMES)}")
    print(f"\nPRODUCT ACTION ITEMS ({len(action_items)}):")
    for item in action_items or ["(none)"]:
        print(f"  ! {item}")
    print(f"\nUNAVAILABLE VERIFIERS ({len(unavailable_items)}):")
    for item in unavailable_items or ["(none)"]:
        print(f"  ~ {item}")
    for ln in fail_detail[:20]:
        print(f"  {ln}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # hard failure only
        print(f"PROJECT SENTINEL crashed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
