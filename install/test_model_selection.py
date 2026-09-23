"""Optional per-part model selection for hermes-ops-kit."""

from __future__ import annotations

import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "scripts"))
sys.path.insert(0, str(KIT / "install"))

from ops_config import resolve_model  # noqa: E402
from render_jobs import render  # noqa: E402


def test_omitted_models_leave_jobs_unpinned():
    cfg = {"models": {}}
    resolved = resolve_model(cfg, "executor")
    assert resolved["provider"] == ""
    assert resolved["model"] == ""
    assert "No fallback configured" in resolved["fallback_line"]

    jobs = {j["id"]: j for j in render(cfg)["jobs"]}
    day = jobs["d4exec1014"]
    assert "model" not in day
    assert "provider" not in day
    assert "Hermes default if unset" in day["prompt"]


def test_default_applies_to_every_agent_part():
    cfg = {
        "models": {
            "default": {"provider": "acme", "model": "acme-1", "fallback": {"provider": "acme", "model": "acme-lite"}}
        }
    }
    for role in ("pm", "executor", "autofix", "ui_live"):
        resolved = resolve_model(cfg, role)
        assert resolved["provider"] == "acme"
        assert resolved["model"] == "acme-1"
        assert resolved["fallback_model"] == "acme-lite"

    jobs = {j["id"]: j for j in render(cfg)["jobs"]}
    day = jobs["d4exec1014"]
    assert day["provider"] == "acme"
    assert day["model"] == "acme-1"
    assert day["fallback_providers"] == [{"provider": "acme", "model": "acme-lite"}]
    assert "acme / acme-lite" in day["prompt"]


def test_per_part_override_does_not_bleed():
    cfg = {
        "models": {
            "default": {"provider": "base", "model": "base-1"},
            "pm": {"provider": "cheap", "model": "cheap-1"},
            "executor": {
                "provider": "code",
                "model": "code-1",
                "fallback": {"provider": "code", "model": "code-2"},
            },
        }
    }
    assert resolve_model(cfg, "market")["model"] == "base-1"
    assert resolve_model(cfg, "pm")["model"] == "cheap-1"
    exec_r = resolve_model(cfg, "executor")
    assert exec_r["model"] == "code-1"
    assert exec_r["fallback_model"] == "code-2"

    jobs = {j["id"]: j for j in render(cfg)["jobs"]}
    assert jobs["c3pm0930"]["model"] == "cheap-1"
    assert jobs["d4exec1014"]["model"] == "code-1"
    assert "fallback_providers" not in jobs["c3pm0930"] or jobs["c3pm0930"].get("fallback_providers") in (None, [])
    assert jobs["d4exec1014"]["fallback_providers"][0]["model"] == "code-2"
