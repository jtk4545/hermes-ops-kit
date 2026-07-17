#!/usr/bin/env python3
"""Shared paths for Hermes brain bus."""

from __future__ import annotations

import os
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", os.path.expandvars(r"%LOCALAPPDATA%\hermes")))
BRAIN_DIR = Path(os.environ.get("HERMES_BRAIN_DIR", str(HERMES_HOME / "brain")))
ROADMAP_FILE = Path(os.path.expanduser("~/.hermes/roadmaps.json"))

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
