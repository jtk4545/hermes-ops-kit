import importlib.util
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_last_amend_date_reads_latest_marker():
    scan = load_module("pipeline-scan")
    body = "fix stuff\nHERMES_AUTOFIX_AMEND: 2026-07-20\nmore\nHERMES_PR_AMEND: 2026-07-23\n"
    assert scan.last_amend_date(body) == "2026-07-23"
    assert scan.last_amend_date("") is None
    assert scan.last_amend_date(None) is None


def test_classify_hermes_pr_amend_vs_hitl():
    scan = load_module("pipeline-scan")
    pr = {
        "number": 12,
        "url": "https://example.com/pr/12",
        "title": "fix",
        "isDraft": False,
        "labels": [{"name": "hermes-exec"}],
        "body": "",
    }
    with patch.object(scan, "pr_checks", return_value=("fail", ["ci:fail"])):
        info = scan.classify_hermes_pr("org/repo", pr, "2026-07-23")
    assert info["action"] == "amend"
    assert info["kind"] == "exec"
    assert info["state"] == "fail"

    pr["body"] = "HERMES_PR_AMEND: 2026-07-23"
    with patch.object(scan, "pr_checks", return_value=("fail", ["ci:fail"])):
        info = scan.classify_hermes_pr("org/repo", pr, "2026-07-23")
    assert info["action"] == "hitl"


def test_classify_skips_draft_and_approval_hold():
    scan = load_module("pipeline-scan")
    draft = {
        "number": 1,
        "url": "u",
        "isDraft": True,
        "labels": [{"name": "hermes-autofix"}],
        "body": "",
    }
    assert scan.classify_hermes_pr("org/repo", draft, "2026-07-23")["action"] == "none"

    hold = {
        "number": 2,
        "url": "u",
        "isDraft": False,
        "labels": [{"name": "hermes-autofix"}, {"name": "hermes-needs-approval"}],
        "body": "",
    }
    assert scan.classify_hermes_pr("org/repo", hold, "2026-07-23")["state"] == "hold"
