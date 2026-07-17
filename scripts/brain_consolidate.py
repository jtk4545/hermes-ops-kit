#!/usr/bin/env python3
"""Merge recent cron artifacts into brain/ and refresh INDEX.md."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR, DEFAULT_BUDGETS, HERMES_HOME, ROADMAP_FILE, SECTIONS  # noqa: E402
from brain_write import _atomic_write, _trim  # noqa: E402

CRON_OUT = HERMES_HOME / "cron" / "output"


def ensure_files() -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    starters = {
        "INDEX.md": "# INDEX\n\nShared Hermes ops brain. Cron + chat read/write these files.\n\n",
        "PRODUCTS.md": "# PRODUCTS\n\nPer-product state and constraints.\n\n",
        "MARKET.md": "# MARKET\n\nMarket snapshots (US sources preferred).\n\n",
        "BUYERS.md": "# BUYERS\n\nBuyers and acquirers pipeline.\n\n",
        "PIPELINES.md": "# PIPELINES\n\nCI/PR and local health digests.\n\n",
        "DECISIONS.md": "# DECISIONS\n\nDurable product decisions from Telegram/HITL.\n\n",
    }
    for name, body in starters.items():
        path = BRAIN_DIR / name
        if not path.exists():
            path.write_text(body, encoding="utf-8")


def recent_cron_notes(limit: int = 8) -> str:
    if not CRON_OUT.is_dir():
        return "(no cron output dir)"
    files = sorted(CRON_OUT.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    bits = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:800]
        except Exception:
            continue
        bits.append(f"### {f.name}\n\n{text}\n")
    return "\n".join(bits) if bits else "(no recent cron outputs)"


def roadmap_summary() -> str:
    if not ROADMAP_FILE.exists():
        return "(roadmap missing)"
    data = json.loads(ROADMAP_FILE.read_text(encoding="utf-8"))
    lines = []
    for proj, phases in sorted(data.items()):
        counts = {ph: len(phases.get(ph, [])) for ph in ["In Progress", "Upcoming", "Backlog", "Done"]}
        if counts["In Progress"] or counts["Upcoming"] or counts["Backlog"]:
            lines.append(
                f"- **{proj}**: in_progress={counts['In Progress']} upcoming={counts['Upcoming']} "
                f"backlog={counts['Backlog']} done={counts['Done']}"
            )
    return "\n".join(lines) if lines else "(empty roadmap)"


def main() -> int:
    ensure_files()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    notes = recent_cron_notes()
    rm = roadmap_summary()

    index_lines = [
        "# INDEX",
        "",
        f"Last consolidate: {stamp}",
        "",
        "## Files",
        "",
    ]
    for key, fname in SECTIONS.items():
        path = BRAIN_DIR / fname
        size = path.stat().st_size if path.exists() else 0
        index_lines.append(f"- `{fname}` ({key}) — {size} bytes")
    index_lines.extend(["", "## Roadmap snapshot", "", rm, "", "## Recent cron outputs", "", notes, ""])
    _atomic_write(BRAIN_DIR / "INDEX.md", _trim("\n".join(index_lines), DEFAULT_BUDGETS["INDEX.md"]))

    products = BRAIN_DIR / "PRODUCTS.md"
    ptxt = products.read_text(encoding="utf-8") if products.exists() else "# PRODUCTS\n\n"
    stamp_line = f"\n_Consolidated {stamp}_\n"
    if "_Consolidated " not in ptxt[-200:]:
        ptxt = _trim(ptxt.rstrip() + stamp_line, DEFAULT_BUDGETS["PRODUCTS.md"])
        _atomic_write(products, ptxt)

    # Silent on success — Telegram only when something goes wrong (non-zero / prints)
    try:
        from sync_quality_skill import main as sync_quality

        sync_quality()
    except Exception as exc:
        print(f"quality skill sync skipped: {exc}", file=sys.stderr)
    try:
        from ops_audit import append_event

        append_event(
            job_id="a1brain0600",
            name="Brain consolidate",
            status="ok",
            summary=f"Refreshed INDEX; roadmap bullets={rm.count('- **')}; synced quality skill",
            artifacts=[str(BRAIN_DIR / "INDEX.md"), str(BRAIN_DIR / "PRINCIPLES.md")],
        )
    except Exception as exc:
        print(f"audit skipped: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
