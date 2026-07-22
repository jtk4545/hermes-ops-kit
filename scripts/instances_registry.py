#!/usr/bin/env python3
"""Load and normalize the non-secret product instance inventory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

STATUSES = {"unknown", "configured", "verified"}
ENVIRONMENTS = {"local", "dev", "staging", "prod"}
SAFE_URL_SCHEMES = {"http", "https"}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _safe_url(value: Any) -> str | None:
    value = _text(value)
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in SAFE_URL_SCHEMES and parsed.netloc:
        return value
    if not parsed.scheme and value.startswith("/") and not value.startswith("//"):
        return value
    return None


def _normalize_record(raw: Any) -> tuple[dict | None, bool]:
    if not isinstance(raw, dict):
        return None, False

    errors: list[str] = []
    invalid = False
    product = _text(raw.get("product")) or "unknown"
    environment = _text(raw.get("environment")) or "unknown"
    if product == "unknown":
        errors.append("product is missing")
        invalid = True
    if environment not in ENVIRONMENTS:
        errors.append("environment must be local, dev, staging, or prod")
        environment = "unknown"
        invalid = True

    raw_url = _text(raw.get("url"))
    url = _safe_url(raw_url)
    if raw_url and not url:
        errors.append("url is not a safe HTTP(S) or local path")
        invalid = True

    evidence_url = _safe_url(raw.get("evidence_url"))
    runbook_url = _safe_url(raw.get("runbook_url"))
    status = _text(raw.get("status")) or "unknown"
    if status not in STATUSES:
        errors.append("status must be unknown, configured, or verified")
        status = "unknown"
        invalid = True

    verified_at = _text(raw.get("verified_at"))
    verified_method = _text(raw.get("verified_method"))
    verified_by = _text(raw.get("verified_by"))
    if status == "verified" and not (verified_at and verified_method and evidence_url):
        errors.append("verified status requires verification evidence, timestamp, and method")
        status = "configured" if url or runbook_url else "unknown"
        verified_at = verified_method = verified_by = None
    if status == "configured" and not (url or runbook_url or evidence_url):
        errors.append("configured status requires a URL, runbook, or evidence")
        status = "unknown"

    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    capabilities = [value.strip() for value in capabilities if isinstance(value, str) and value.strip()]

    return {
        "product": product,
        "environment": environment,
        "status": status,
        "url": url,
        "runbook_url": runbook_url,
        "capabilities": capabilities,
        "owner": _text(raw.get("owner")),
        "evidence_url": evidence_url,
        "verified_at": verified_at,
        "verified_method": verified_method,
        "verified_by": verified_by,
        "notes": _text(raw.get("notes")),
        "validation_errors": errors,
    }, invalid


def load_instance_registry(path: Path) -> dict:
    """Return a safe payload; bad/missing data never becomes a health claim."""
    source = str(path)
    if not path.is_file():
        return {
            "count": 0,
            "invalid_count": 0,
            "source": source,
            "instances": [],
            "errors": ["registry source is missing"],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "count": 0,
            "invalid_count": 0,
            "source": source,
            "instances": [],
            "errors": ["registry source is unreadable or invalid JSON"],
        }

    raw_instances = data.get("instances", []) if isinstance(data, dict) else []
    if not isinstance(raw_instances, list):
        raw_instances = []
    instances: list[dict] = []
    invalid_count = 0
    for raw in raw_instances:
        record, invalid = _normalize_record(raw)
        if record is None:
            continue
        instances.append(record)
        invalid_count += int(invalid)
    return {
        "count": len(instances),
        "invalid_count": invalid_count,
        "source": source,
        "instances": instances,
        "errors": [],
    }


def record_instance_verification(
    path: Path,
    *,
    product: str,
    environment: str,
    method: str,
    evidence_url: str,
    note: str,
    actor: str = "human",
    now: str | None = None,
) -> dict:
    """Record explicit human evidence for one existing inventory entry."""
    product = _text(product) or ""
    environment = _text(environment) or ""
    method = _text(method) or ""
    evidence_url = _safe_url(evidence_url) or ""
    note = _text(note) or ""
    actor = _text(actor) or "human"
    if not product or environment not in ENVIRONMENTS:
        raise ValueError("product and a valid environment are required")
    if not method:
        raise ValueError("method is required")
    if not evidence_url:
        raise ValueError("evidence_url must be a safe HTTP(S) or local path")
    if not note:
        raise ValueError("note is required")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("registry source is unreadable or invalid JSON") from exc
    instances = data.get("instances") if isinstance(data, dict) else None
    if not isinstance(instances, list):
        raise ValueError("registry instances must be a list")
    match = next(
        (
            item
            for item in instances
            if isinstance(item, dict)
            and item.get("product") == product
            and item.get("environment") == environment
        ),
        None,
    )
    if match is None:
        raise KeyError(f"instance not found: {product}/{environment}")

    match.update(
        {
            "status": "verified",
            "evidence_url": evidence_url,
            "verified_at": now or datetime.now(timezone.utc).isoformat(),
            "verified_method": method,
            "verified_by": actor,
            "notes": note,
        }
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return load_instance_registry(path)
