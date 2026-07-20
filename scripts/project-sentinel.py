#!/usr/bin/env python3
"""Project Sentinel — daily local health-check digest for all user projects.

Tool resolution (avoid false FAIL when cron PATH is thin):
  - ruff: <repo>/.venv (or venv) Scripts/bin, else PATH
  - tsc/eslint: node + <repo>/node_modules/... (not bare npx if local install exists)
  - Hermes-bundled node prepended to PATH when present
Missing verifiers → UNAVAILABLE (ops gap), not product FAIL.

Checks come from ops-config.yaml → projects.*.checks (via ops_config.sentinel_projects).
Argv tokens may use placeholders resolved at runtime:
  {python}  — sys.executable
  {node}    — resolved node binary
  {ruff}    — repo venv ruff or PATH
  {tsc} / {eslint} — local node_modules via node (or npx fallback)
  {go}      — go on PATH / common install locations / HERMES_GO
  {gradlew} — ./gradlew(.bat) when Java is available
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
# Cron shells do not consistently export HERMES_HOME. Pin to install root
# (…/hermes/scripts/this.py → parent is HERMES_HOME).
os.environ.setdefault("HERMES_HOME", str(SCRIPTS.parent))

from hermes_paths import brain_dir  # noqa: E402
from ops_config import projects_root, sentinel_projects  # noqa: E402

BASE = projects_root()
BRAIN_DIR = brain_dir()
# Thin cron PATH may omit Hermes-bundled Node (common on Windows installs).
NODE_BIN = SCRIPTS.parent / "node"
if NODE_BIN.is_dir():
    os.environ["PATH"] = str(NODE_BIN) + os.pathsep + os.environ.get("PATH", "")

PROJECTS = sentinel_projects()


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
            return ["cmd", "/c", str(p)]
        if p.name == bin_name and (repo / "node_modules" / package / "bin").is_dir():
            pkg_bin = repo / "node_modules" / package / "bin" / bin_name
            pkg_js = repo / "node_modules" / package / "bin" / f"{bin_name}.js"
            if pkg_js.is_file():
                return [node, str(pkg_js)]
            if pkg_bin.is_file():
                return [node, str(pkg_bin)]
        if p.suffix.lower() == ".js" or package in str(p):
            return [node, str(p)]
    npx = _which("npx")
    if npx and node:
        if os.name == "nt":
            return ["cmd", "/c", "npx", "--yes", "-p", package, bin_name]
        return ["npx", "--yes", "-p", package, bin_name]
    return None


def go_cmd() -> str | None:
    """Resolve go: PATH, then common local install locations."""
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
        Path("/usr/local/go/bin/go"),
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
        Path("/usr/lib/jvm"),
    ):
        if p.is_file():
            candidates.append(p)
        elif p.is_dir():
            pattern = "java.exe" if os.name == "nt" else "java"
            for match in sorted(p.rglob(pattern))[:5]:
                candidates.append(match)

    for java in candidates:
        if not java.is_file():
            continue
        home = java.parent.parent
        if (home / "bin").is_dir():
            os.environ.setdefault("JAVA_HOME", str(home))
            os.environ["PATH"] = str(home / "bin") + os.pathsep + os.environ.get("PATH", "")
            return str(java)
    return None


def gradle_cmd(repo: Path) -> list[str] | None:
    if not ensure_java_home() and not _which("java"):
        return None
    if os.name == "nt":
        bat = repo / "gradlew.bat"
        if bat.is_file():
            return ["cmd", "/c", str(bat)]
    sh = repo / "gradlew"
    if sh.is_file():
        return [str(sh)]
    return None


def resolve_check_cmd(repo: Path, cmd: list[str]) -> list[str] | None:
    """Expand placeholders; return None if a required tool is missing."""
    if not cmd:
        return None
    out: list[str] = []
    for tok in cmd:
        if tok == "{python}":
            out.append(sys.executable)
            continue
        if tok == "{node}":
            node = resolve_node()
            if not node:
                return None
            out.append(node)
            continue
        if tok == "{ruff}":
            ruff = resolve_ruff(repo)
            if not ruff:
                return None
            out.extend(ruff)
            continue
        if tok == "{tsc}":
            tsc = resolve_js_tool(repo, "typescript", "tsc")
            if not tsc:
                return None
            out.extend(tsc)
            continue
        if tok == "{eslint}":
            eslint = resolve_js_tool(repo, "eslint", "eslint")
            if not eslint:
                return None
            out.extend(eslint)
            continue
        if tok == "{go}":
            go = go_cmd()
            if not go:
                return None
            out.append(go)
            continue
        if tok == "{gradlew}":
            g = gradle_cmd(repo)
            if not g:
                return None
            out.extend(g)
            continue
        if tok.startswith("{") and tok.endswith("}"):
            return None
        out.append(tok)
    return out


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


def _looks_like_missing_tool(lines: list[str]) -> bool:
    text = "\n".join(lines).lower()
    needles = (
        "command not found:",
        "java_home is not set",
        "no 'java' command",
        "unable to locate a java runtime",
        "is not recognized as an internal",
        "executable file not found",
    )
    return any(n in text for n in needles)


def write_brain_health(
    results: list[dict], action_items: list[str], unavailable_items: list[str]
) -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    pipe = BRAIN_DIR / "PIPELINES.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## Local health (sentinel) — {stamp}",
        "",
    ]
    for row in results:
        lines.append(f"- **{row['project']}**: {row['status']} — {row['summary']}")
    if action_items:
        lines.append("")
        lines.append("### Action items")
        for item in action_items:
            lines.append(f"- {item}")
    if unavailable_items:
        lines.append("")
        lines.append("### Unavailable verifiers (ops tooling)")
        for item in unavailable_items:
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

    for proj_name, proj in PROJECTS.items():
        path: Path = proj["path"]
        if not path.is_dir():
            action_items.append(f"{proj_name}: directory not found")
            results.append(
                {"project": proj_name, "status": "FAIL", "summary": "missing directory"}
            )
            continue

        fails: list[str] = []
        unavailable: list[str] = []
        for desc, cmd_tmpl in proj["checks"]:
            cmd = resolve_check_cmd(path, list(cmd_tmpl))
            if cmd is None:
                unavailable.append(desc)
                unavailable_items.append(
                    f"{proj_name}: {desc} unavailable (tool not in repo venv/node_modules or PATH)"
                )
                continue
            timeout = 300 if any("gradle" in t.lower() for t in cmd) else 180
            ok, lines = run_cmd(cmd, cwd=path, timeout=timeout)
            if not ok:
                if _looks_like_missing_tool(lines):
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

    present = sum(1 for p in PROJECTS.values() if p["path"].is_dir())
    try:
        write_brain_health(results, action_items, unavailable_items)
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
                f"Health check {present}/{len(PROJECTS)} present; "
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
    print(f"Projects present: {present}/{len(PROJECTS)}")
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
