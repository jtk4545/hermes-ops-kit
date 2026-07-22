#!/usr/bin/env python3
"""Configurable human-notification window policy."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ops_config import notify_window, timezone_name

TZ = ZoneInfo(timezone_name())
WEEKEND_HITL_PREFIX = "WEEKEND-DEFER:"
WINDOW = notify_window()
NOTIFY_WEEKDAYS = {
    int(day) for day in WINDOW.get("weekdays", [0, 1, 2, 3, 4])
}
ALWAYS_ALLOW_JOBS = {
    str(job_id) for job_id in WINDOW.get("always_allow_jobs", ["f6ops2100"])
}


def _parse_clock(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        hour, minute = str(value).split(":", 1)
        return int(hour), int(minute)
    except (TypeError, ValueError):
        return fallback


NOTIFY_START = _parse_clock(WINDOW.get("start", "09:00"), (9, 0))
NOTIFY_END = _parse_clock(WINDOW.get("end", "17:00"), (17, 0))


def now_local() -> datetime:
    return datetime.now(TZ)


def now_chicago() -> datetime:
    return now_local()


def _as_local(when: datetime | None = None) -> datetime:
    dt = when or now_local()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def is_weekend(when: datetime | None = None) -> bool:
    return _as_local(when).weekday() >= 5


def in_notify_window(when: datetime | None = None) -> bool:
    """Whether ordinary HITL/alert delivery is allowed right now."""
    dt = _as_local(when)
    if dt.weekday() not in NOTIFY_WEEKDAYS:
        return False
    minutes = dt.hour * 60 + dt.minute
    start = NOTIFY_START[0] * 60 + NOTIFY_START[1]
    end = NOTIFY_END[0] * 60 + NOTIFY_END[1]
    return start <= minutes <= end


def telegram_hitl_allowed(when: datetime | None = None) -> bool:
    return in_notify_window(when)


def telegram_allowed_for_job(
    job_id: str | None = None,
    when: datetime | None = None,
) -> bool:
    return (job_id or "").strip() in ALWAYS_ALLOW_JOBS or in_notify_window(when)


def next_notify_window_start(when: datetime | None = None) -> datetime:
    """Return the next configured weekday/window start."""
    dt = _as_local(when)
    start_today = dt.replace(
        hour=NOTIFY_START[0],
        minute=NOTIFY_START[1],
        second=0,
        microsecond=0,
    )
    if dt.weekday() in NOTIFY_WEEKDAYS and dt < start_today:
        return start_today
    candidate = start_today + timedelta(days=1)
    while candidate.weekday() not in NOTIFY_WEEKDAYS:
        candidate += timedelta(days=1)
    return candidate


def weekend_defer_reason(reason: str) -> str:
    r = (reason or "").strip()
    if r.upper().startswith(WEEKEND_HITL_PREFIX):
        return r
    if not r:
        return f"{WEEKEND_HITL_PREFIX} ACTION: needs human — deferred to weekday"
    return f"{WEEKEND_HITL_PREFIX} {r}"
