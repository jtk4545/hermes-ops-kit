#!/usr/bin/env python3
"""Portable Hermes path resolution (Windows / macOS / Linux).

Prefer setting HERMES_HOME explicitly. When unset:

  Windows:  %LOCALAPPDATA%/hermes
  Unix:     $XDG_DATA_HOME/hermes  or  ~/.local/share/hermes
            (reuses ~/.hermes-home if that directory already exists)

Interactive mirrors / roadmaps live under ~/.hermes (always).
"""

from __future__ import annotations

import os
from pathlib import Path


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME", "").strip()
    if env:
        return Path(env).expanduser()

    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "hermes"

    legacy = Path.home() / ".hermes-home"
    xdg_env = os.environ.get("XDG_DATA_HOME", "").strip()
    xdg = Path(xdg_env) / "hermes" if xdg_env else Path.home() / ".local" / "share" / "hermes"
    for candidate in (legacy, xdg):
        if candidate.is_dir():
            return candidate
    return xdg


def brain_dir() -> Path:
    env = os.environ.get("HERMES_BRAIN_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return hermes_home() / "brain"


def dot_hermes() -> Path:
    return Path.home() / ".hermes"


def roadmap_file() -> Path:
    return dot_hermes() / "roadmaps.json"
