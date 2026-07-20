#!/usr/bin/env python3
"""Shared paths for Hermes brain bus."""

from __future__ import annotations

from hermes_paths import brain_dir, hermes_home, roadmap_file

HERMES_HOME = hermes_home()
BRAIN_DIR = brain_dir()
ROADMAP_FILE = roadmap_file()

SECTIONS = {
    "INDEX": "INDEX.md",
    "PRODUCTS": "PRODUCTS.md",
    "MARKET": "MARKET.md",
    "BUYERS": "BUYERS.md",
    "PIPELINES": "PIPELINES.md",
    "DECISIONS": "DECISIONS.md",
    "PRINCIPLES": "PRINCIPLES.md",
    "PR_QUALITY": "PR_QUALITY.md",
}

DEFAULT_BUDGETS = {
    "INDEX.md": 4000,
    "PRODUCTS.md": 12000,
    "MARKET.md": 12000,
    "BUYERS.md": 8000,
    "PIPELINES.md": 12000,
    "DECISIONS.md": 8000,
    "PRINCIPLES.md": 12000,
    "PR_QUALITY.md": 16000,
}
