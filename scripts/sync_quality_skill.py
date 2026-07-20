#!/usr/bin/env python3
"""Regenerate skills/software-development/quality-principles/SKILL.md from brain SoT."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain_paths import BRAIN_DIR, HERMES_HOME  # noqa: E402

SKILL_PATH = (
    HERMES_HOME
    / "skills"
    / "software-development"
    / "quality-principles"
    / "SKILL.md"
)

FRONTMATTER = """---
name: quality-principles
description: Use for every PM, market research, roadmap executor, and CI autofix turn. Loads product-specific quality bars and per-repo PR lessons from the brain (PRINCIPLES + PR_QUALITY). Update the brain when you learn lasting lessons.
version: 1.0.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [quality, principles, pr, executor, pm, market, autofix]
    related_skills: [brain, dev-test-loop, roadmap, human-approval, auto-pr-fixer]
---

# Quality principles (generated from brain)

> **Do not hand-edit this file.** Edit `$HERMES_HOME/brain/PRINCIPLES.md` and `PR_QUALITY.md`, then run `python sync_quality_skill.py` (also run from brain consolidate).

"""


def main() -> int:
    principles = BRAIN_DIR / "PRINCIPLES.md"
    prq = BRAIN_DIR / "PR_QUALITY.md"
    if not principles.is_file() or not prq.is_file():
        print("Missing PRINCIPLES.md or PR_QUALITY.md in brain", file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = (
        FRONTMATTER
        + f"_Synced {stamp}_\n\n"
        + "## How to use\n\n"
        + "1. `brain_read.py --sections PRINCIPLES,PR_QUALITY,PRODUCTS` (always before acting).\n"
        + "2. Follow the role section that matches this job (Executor / Product manager / Market research / CI autofix).\n"
        + "3. For code PRs, obey the repo section under PR_QUALITY.\n"
        + "4. After lasting lessons: `brain_write.py PR_QUALITY --append` (repo lesson) and/or "
        + "`brain_write.py PRINCIPLES --append` (cross-product rule).\n"
        + "5. Re-run `sync_quality_skill.py` after brain edits (consolidate does this).\n\n"
        + "---\n\n"
        + principles.read_text(encoding="utf-8")
        + "\n\n---\n\n"
        + prq.read_text(encoding="utf-8")
    )

    SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKILL_PATH.write_text(body, encoding="utf-8")
    # Mirror under ~/.hermes when present
    mirror = Path.home() / ".hermes" / "skills" / "software-development" / "quality-principles" / "SKILL.md"
    try:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(body, encoding="utf-8")
    except OSError:
        pass

    print(f"Wrote {SKILL_PATH} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
