#!/usr/bin/env python3
"""Weekend ops policy helpers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ops_config import timezone_name

TZ = ZoneInfo(timezone_name())
WEEKEND_HITL_PREFIX = "WEEKEND-DEFER:"


def now_local() -> datetime:
    return datetime.now(TZ)


def now_chicago() -> datetime:
    return now_local()


def is_weekend(when: datetime | None = None) -> bool:
    dt = when or now_local()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    else:
        dt = dt.astimezone(TZ)
    return dt.weekday() >= 5


def weekend_defer_reason(reason: str) -> str:
    r = (reason or "").strip()
    if r.upper().startswith(WEEKEND_HITL_PREFIX):
        return r
    if not r:
        return f"{WEEKEND_HITL_PREFIX} ACTION: needs human — deferred to weekday"
    return f"{WEEKEND_HITL_PREFIX} {r}"
