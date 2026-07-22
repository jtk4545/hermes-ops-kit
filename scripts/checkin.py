#!/usr/bin/env python3
"""Human check-in payload for the ops dashboard (weekday HITL windows)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from hermes_paths import brain_dir, hermes_home, roadmap_file
except Exception:  # pragma: no cover
    def hermes_home() -> Path:
        env = os.environ.get("HERMES_HOME", "").strip()
        if env:
            return Path(env)
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            return Path(local) / "hermes"
        return Path.home() / ".local" / "share" / "hermes"

    def brain_dir() -> Path:
        return hermes_home() / "brain"

    def roadmap_file() -> Path:
        return Path.home() / ".hermes" / "roadmaps.json"

try:
    from weekend_policy import in_notify_window, next_notify_window_start, now_chicago
except Exception:  # pragma: no cover
    TZ = ZoneInfo("America/Chicago")

    def now_chicago() -> datetime:
        return datetime.now(TZ)

    def in_notify_window(when=None) -> bool:
        return True

    def next_notify_window_start(when=None) -> datetime:
        return now_chicago()


TZ = ZoneInfo("America/Chicago")
HERMES_HOME = hermes_home()
ROADMAP_FILE = roadmap_file()
BRAIN_DIR = brain_dir()
PIPELINES = BRAIN_DIR / "PIPELINES.md"
HQ_STATE = HERMES_HOME / "state" / "human_queue.json"
# GitHub logins that count as "Hermes" for approval HITL.
# Override with comma-separated HERMES_GH_AUTHORS; default is a generic placeholder.
DEFAULT_HERMES_GH_AUTHORS = ("hermes-bot",)


def hermes_gh_authors() -> set[str]:
    raw = (os.environ.get("HERMES_GH_AUTHORS") or "").strip()
    if raw:
        return {p.strip().lower() for p in raw.split(",") if p.strip()}
    return {a.lower() for a in DEFAULT_HERMES_GH_AUTHORS}


def is_hermes_author(login: str | None) -> bool:
    return (login or "").strip().lower() in hermes_gh_authors()


def _repo_slugs() -> list[str]:
    try:
        from ops_config import repo_slugs

        slugs = repo_slugs()
        if slugs:
            return list(slugs)
    except Exception:
        pass
    try:
        from gh_ops import REPOS

        return list(REPOS or [])
    except Exception:
        return []


def _label_names(pr: dict) -> list[str]:
    labels = pr.get("labels") or []
    names: list[str] = []
    for lb in labels:
        if isinstance(lb, dict):
            n = (lb.get("name") or "").strip()
        else:
            n = str(lb).strip()
        if n:
            names.append(n)
    return names


def _pr_flag(pr: dict, *, author_login: str = "") -> str:
    """Single status chip for check-in UI.

    APPROVAL is only for PRs authored by the Hermes GitHub user — human/other
    authors needing review are left as OPEN so the queue stays bot-HITL only.
    """
    labels = {n.lower() for n in _label_names(pr)}
    mss = (pr.get("mergeStateStatus") or "").upper()
    rd = (pr.get("reviewDecision") or "").upper()
    if pr.get("isDraft"):
        return "DRAFT"
    if mss == "DIRTY":
        return "CONFLICT"
    needs_review = "hermes-needs-approval" in labels or rd in (
        "REVIEW_REQUIRED",
        "CHANGES_REQUESTED",
    )
    if needs_review:
        if is_hermes_author(author_login):
            return "APPROVAL"
        return "OPEN"
    if mss == "BEHIND":
        return "BEHIND"
    if rd == "APPROVED" or "hermes-approved" in labels:
        return "APPROVED"
    if mss in ("CLEAN", "HAS_HOOKS", "UNSTABLE", ""):
        return "OPEN"
    return mss or "OPEN"


PHASES = ["In Progress", "Upcoming", "Backlog", "Done"]

# Named check-in windows (America/Chicago, weekdays). minutes_from / minutes_to inclusive.
# Schedule-agnostic copy — no product or model names.
SLOTS = [
    {
        "id": "morning_open",
        "label": "Morning open",
        "start": (9, 15),
        "end": (9, 45),
        "why": "After overnight work + morning scans. Clear approvals before the first day executor window.",
        "checklist": [
            "Approve or hold overnight / hermes-autofix PRs (comment `yes` or label hermes-approved)",
            "Clear roadmap APPROVAL / ACTION blocks with exact next step done",
            "Skim sentinel / infra notes in PIPELINES if anything red from morning scans",
            "Release blocked items back to agent when your action is done",
        ],
    },
    {
        "id": "post_exec_am",
        "label": "After day exec #1",
        "start": (10, 30),
        "end": (11, 30),
        "why": "Morning executor may have opened PRs or hit human gates.",
        "checklist": [
            "Review new hermes-exec PRs — approve green ones or comment what’s wrong",
            "Handle new ACTION: human_actions on roadmap (secrets, clicks, prod gates)",
            "If a PR is DIRTY/conflicts — resolve or tell agent how to proceed",
            "Check human-queue items that just became due",
        ],
    },
    {
        "id": "pre_exec_pm",
        "label": "Pre-afternoon exec",
        "start": (13, 30),
        "end": (14, 0),
        "why": "Unstick human items so the afternoon executor isn’t idle on your blockers.",
        "checklist": [
            "Anything still blocked on you? Do it or re-scope / unassign",
            "Approve lingering green PRs so merge-on-green can land before afternoon work",
            "Confirm no DIRTY bot PR is pinning a repo the executor needs",
        ],
    },
    {
        "id": "close_of_day",
        "label": "Close of business",
        "start": (15, 45),
        "end": (16, 45),
        "why": "After afternoon autofix — last chance for PR monitor to merge before quiet hours.",
        "checklist": [
            "Final PR approvals (must be in before quiet hours for same-day merge nags)",
            "Triage autofix failures — approve fix PR or leave a hold reason",
            "Leave clear human_actions on anything that must wait until tomorrow",
            "Optional: note wins/blockers for the evening ops report (no action required now)",
        ],
    },
]


def _mins(h: int, m: int) -> int:
    return h * 60 + m


def _slot_bounds(slot: dict) -> tuple[int, int]:
    sh, sm = slot["start"]
    eh, em = slot["end"]
    return _mins(sh, sm), _mins(eh, em)


def pick_slot(now: datetime | None = None) -> dict:
    """Return current / nearest check-in slot metadata."""
    dt = now or now_chicago()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    else:
        dt = dt.astimezone(TZ)

    weekday = dt.weekday() < 5
    cur = _mins(dt.hour, dt.minute)

    result = {
        "now_ct": dt.isoformat(),
        "weekday": weekday,
        "in_hitl_window": in_notify_window(dt),
        "active": None,
        "next": None,
        "all_slots": [],
    }

    for s in SLOTS:
        a, b = _slot_bounds(s)
        sh, sm = s["start"]
        eh, em = s["end"]
        entry = {
            "id": s["id"],
            "label": s["label"],
            "window": f"{sh:02d}:{sm:02d}–{eh:02d}:{em:02d} CT",
            "why": s["why"],
            "checklist": list(s["checklist"]),
            "is_now": False,
            "is_past_today": False,
            "is_upcoming_today": False,
        }
        if weekday and a <= cur <= b:
            entry["is_now"] = True
            result["active"] = entry
        elif weekday and cur > b:
            entry["is_past_today"] = True
        elif weekday and cur < a:
            entry["is_upcoming_today"] = True
        result["all_slots"].append(entry)

    if result["active"] is None:
        # next slot today or next business-day morning_open
        if weekday:
            for entry in result["all_slots"]:
                if entry["is_upcoming_today"]:
                    result["next"] = entry
                    break
        if result["next"] is None:
            nxt = next_notify_window_start(dt)
            s0 = SLOTS[0]
            sh, sm = s0["start"]
            eh, em = s0["end"]
            result["next"] = {
                "id": s0["id"],
                "label": s0["label"],
                "window": f"{sh:02d}:{sm:02d}–{eh:02d}:{em:02d} CT",
                "why": s0["why"],
                "checklist": list(s0["checklist"]),
                "when_date": nxt.date().isoformat(),
                "is_now": False,
            }

    return result


def load_needs_you() -> list[dict]:
    if not ROADMAP_FILE.is_file():
        return []
    try:
        data = json.loads(ROADMAP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[dict] = []
    for proj, phases in (data or {}).items():
        if not isinstance(phases, dict):
            continue
        for ph in PHASES:
            if ph == "Done":
                continue
            for item in phases.get(ph) or []:
                if not isinstance(item, dict):
                    continue
                blocked = bool(item.get("blocked"))
                owner = (item.get("owner") or "agent").lower()
                if not blocked and owner != "human":
                    continue
                reason = (item.get("blocked_reason") or "").strip()
                kind = "HUMAN"
                up = reason.upper()
                if up.startswith("APPROVAL:"):
                    kind = "APPROVAL"
                elif up.startswith("ACTION:") or blocked:
                    kind = "ACTION" if blocked else kind
                out.append(
                    {
                        "project": proj,
                        "phase": ph,
                        "id": item.get("id"),
                        "name": item.get("name") or "(unnamed)",
                        "kind": kind,
                        "owner": owner,
                        "blocked": blocked,
                        "blocked_reason": reason,
                        "human_actions": item.get("human_actions") or [],
                        "notes": (item.get("notes") or "")[:400],
                        "priority": item.get("priority"),
                    }
                )

    def sort_key(r: dict):
        kind_order = {"APPROVAL": 0, "ACTION": 1, "HUMAN": 2}
        phase_order = {"In Progress": 0, "Upcoming": 1, "Backlog": 2}
        return (
            kind_order.get(r["kind"], 9),
            phase_order.get(r.get("phase") or "", 9),
            r.get("priority") or 9,
            r["project"],
            r["name"],
        )

    out.sort(key=sort_key)
    return out


def _normalize_open_pr_item(item: dict) -> dict:
    """Recompute APPROVAL flag so cache stays correct after policy changes."""
    out = dict(item)
    author = out.get("author") or ""
    fake = {
        "isDraft": out.get("is_draft"),
        "labels": [{"name": n} for n in (out.get("labels") or [])],
        "mergeStateStatus": out.get("merge_state") or "",
        "reviewDecision": out.get("review_decision") or "",
    }
    out["flag"] = _pr_flag(fake, author_login=str(author))
    out["is_hermes_author"] = is_hermes_author(str(author))
    return out


def load_open_prs(*, cache_ttl_sec: int = 120, force_refresh: bool = False) -> dict:
    """All open PRs across configured repos (cached briefly for UI snappiness)."""
    cache_path = HERMES_HOME / "state" / "open_prs.json"
    now = now_chicago()
    authors = sorted(hermes_gh_authors())
    if not force_refresh and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            ts = cached.get("fetched_at") or ""
            if ts:
                fetched = datetime.fromisoformat(ts)
                if fetched.tzinfo is None:
                    fetched = fetched.replace(tzinfo=TZ)
                age = (now - fetched.astimezone(TZ)).total_seconds()
                if age >= 0 and age < cache_ttl_sec and isinstance(cached.get("items"), list):
                    items = [_normalize_open_pr_item(i) for i in cached["items"] if isinstance(i, dict)]
                    cached = dict(cached)
                    cached["items"] = items
                    cached["count"] = len(items)
                    cached["hermes_authors"] = authors
                    cached["cache_hit"] = True
                    cached["cache_age_sec"] = int(age)
                    return cached
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

    items: list[dict] = []
    errors: list[str] = []
    try:
        from gh_ops import apply_token_env, gh_json

        apply_token_env()
        fields = (
            "number,title,url,author,isDraft,labels,reviewDecision,"
            "mergeStateStatus,updatedAt,createdAt,headRefName"
        )
        for slug in _repo_slugs():
            prs = gh_json(
                [
                    "pr",
                    "list",
                    "--repo",
                    slug,
                    "--state",
                    "open",
                    "--limit",
                    "40",
                    "--json",
                    fields,
                ],
                timeout=45,
            )
            if prs is None:
                errors.append(f"{slug}: list failed")
                continue
            if not isinstance(prs, list):
                continue
            for pr in prs:
                if not isinstance(pr, dict):
                    continue
                author = pr.get("author") or {}
                login = author.get("login") if isinstance(author, dict) else str(author or "")
                labels = _label_names(pr)
                items.append(
                    {
                        "repo": slug,
                        "number": pr.get("number"),
                        "title": pr.get("title") or "",
                        "url": pr.get("url") or f"https://github.com/{slug}/pull/{pr.get('number')}",
                        "author": login,
                        "is_draft": bool(pr.get("isDraft")),
                        "labels": labels,
                        "review_decision": pr.get("reviewDecision") or "",
                        "merge_state": pr.get("mergeStateStatus") or "",
                        "updated_at": pr.get("updatedAt") or "",
                        "created_at": pr.get("createdAt") or "",
                        "head_ref": pr.get("headRefName") or "",
                        "flag": _pr_flag(pr, author_login=str(login)),
                        "is_hermes_author": is_hermes_author(str(login)),
                    }
                )
    except Exception as exc:  # pragma: no cover
        errors.append(str(exc))

    flag_rank = {
        "CONFLICT": 0,
        "APPROVAL": 1,
        "BEHIND": 2,
        "APPROVED": 3,
        "OPEN": 4,
        "DRAFT": 5,
    }
    items.sort(
        key=lambda r: (
            flag_rank.get(r.get("flag") or "", 9),
            r.get("repo") or "",
            -(r.get("number") or 0),
        )
    )

    payload = {
        "fetched_at": now.isoformat(),
        "cache_hit": False,
        "cache_age_sec": 0,
        "count": len(items),
        "items": items,
        "errors": errors,
        "source": "gh pr list",
        "hermes_authors": authors,
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return payload


def load_pr_section() -> dict:
    """Parse PR monitor bullet block from PIPELINES.md if present."""
    result = {
        "source": str(PIPELINES),
        "updated_line": None,
        "items": [],
        "raw_present": False,
    }
    if not PIPELINES.is_file():
        return result
    try:
        text = PIPELINES.read_text(encoding="utf-8")
    except OSError:
        return result

    m = re.search(
        r"(?is)##\s*PR monitor.*?(?=^##\s|\Z)",
        text,
    )
    block = m.group(0) if m else ""
    if not block:
        lines = [
            ln
            for ln in text.splitlines()
            if re.search(r"hermes-(exec|autofix)|APPROVAL|CONFLICT|PR #", ln, re.I)
        ]
        block = "\n".join(lines[-40:])
    else:
        result["raw_present"] = True

    for ln in block.splitlines():
        if "updated" in ln.lower() and ln.strip().startswith("#"):
            result["updated_line"] = ln.strip()
        if not ln.strip().startswith(("-", "*")):
            continue
        item = {"text": ln.strip().lstrip("-* ").strip()}
        t = item["text"].upper()
        if "APPROVAL" in t or "NEEDS-APPROVAL" in t or "HERMES-NEEDS-APPROVAL" in t:
            item["flag"] = "APPROVAL"
        elif "CONFLICT" in t or "DIRTY" in t:
            item["flag"] = "CONFLICT"
        elif "RED" in t or "FAIL" in t:
            item["flag"] = "RED"
        elif "MERGED" in t:
            item["flag"] = "MERGED"
        elif "BEHIND" in t or "UPDATE" in t:
            item["flag"] = "BEHIND"
        else:
            item["flag"] = "INFO"
        result["items"].append(item)
    return result


def load_human_queue_state() -> dict:
    if not HQ_STATE.is_file():
        return {"path": str(HQ_STATE), "entries": []}
    try:
        data = json.loads(HQ_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(HQ_STATE), "entries": [], "error": "unreadable"}
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        entries = list((entries or {}).values()) if isinstance(entries, dict) else []
    slim = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        slim.append(
            {
                "key": e.get("key") or e.get("id"),
                "title": e.get("title") or e.get("name"),
                "kind": e.get("kind"),
                "alert_count": e.get("alert_count"),
                "next_alert_at": e.get("next_alert_at"),
                "last_alert_at": e.get("last_alert_at"),
                "window_suppressed": e.get("window_suppressed") or e.get("weekend_suppressed"),
            }
        )
    return {"path": str(HQ_STATE), "entries": slim}


def checkin_payload(*, refresh_prs: bool = False) -> dict:
    slots = pick_slot()
    needs = load_needs_you()
    prs = load_pr_section()
    open_prs_all = load_open_prs(force_refresh=refresh_prs)
    hq = load_human_queue_state()

    # Check-in only surfaces Hermes bot PRs (not every open PR across repos).
    all_items = [i for i in (open_prs_all.get("items") or []) if isinstance(i, dict)]
    hermes_items = [
        i
        for i in all_items
        if i.get("is_hermes_author") or is_hermes_author(str(i.get("author") or ""))
    ]
    open_prs = dict(open_prs_all)
    open_prs["items"] = hermes_items
    open_prs["count"] = len(hermes_items)
    open_prs["count_all_open"] = len(all_items)
    open_prs["filter"] = "hermes_author"

    approvals = [n for n in needs if n["kind"] == "APPROVAL"]
    actions = [n for n in needs if n["kind"] == "ACTION"]
    humans = [n for n in needs if n["kind"] == "HUMAN"]
    pr_approvals = [i for i in prs.get("items") or [] if i.get("flag") == "APPROVAL"]
    pr_conflicts = [i for i in prs.get("items") or [] if i.get("flag") == "CONFLICT"]
    open_need = [
        i
        for i in hermes_items
        if (i.get("flag") or "") in ("APPROVAL", "CONFLICT", "BEHIND")
    ]
    hermes_approvals = [i for i in hermes_items if (i.get("flag") or "") == "APPROVAL"]

    focus = slots.get("active") or slots.get("next")
    summary = {
        "needs_you_total": len(needs),
        "approvals": len(approvals),
        "actions": len(actions),
        "human_owner": len(humans),
        "pr_flags_approval": len(pr_approvals),
        "pr_flags_conflict": len(pr_conflicts),
        "open_prs": len(hermes_items),
        "open_prs_all": len(all_items),
        "open_prs_attention": len(open_need),
        "hermes_pr_approvals": len(hermes_approvals),
        "human_queue_entries": len(hq.get("entries") or []),
        "telegram_hitl_open": slots["in_hitl_window"],
    }

    do_now = []
    if summary["approvals"] or summary["pr_flags_approval"] or hermes_approvals:
        do_now.append("Review Hermes bot PRs tagged APPROVAL (+ roadmap approvals)")
    if summary["actions"]:
        do_now.append("Work ACTION human_actions (exact steps on each card)")
    if summary["pr_flags_conflict"] or any(
        (i.get("flag") == "CONFLICT") for i in hermes_items
    ):
        do_now.append("Resolve CONFLICT/DIRTY Hermes bot PRs or re-scope")
    if summary["human_owner"] and not summary["actions"]:
        do_now.append("Owner=human items waiting — advance or hand back to agent")
    if not do_now:
        do_now.append("Nothing queued — optional skim checklist only")

    return {
        "generated_at": now_chicago().isoformat(),
        "slots": slots,
        "focus": focus,
        "summary": summary,
        "do_now": do_now,
        "needs_you": needs,
        "open_prs": open_prs,
        "pr_monitor": prs,
        "human_queue": hq,
        "links": {
            "roadmap_needs_you": "/?view=needs_you",
            "roadmap": "/",
            "instances": "/instances",
            "jobs": "/jobs",
            "audit": "/audit",
            "checkin": "/checkin",
        },
        "lan_urls": _lan_urls(),
        "policy": {
            "telegram": "Weekday HITL window (ops-config notify_window) + evening ops report",
            "merges": "PR monitor runs 24/7; approval nags only in HITL window",
            "open_prs_filter": "hermes_author_only",
        },
    }


def _lan_urls() -> list[str]:
    urls: list[str] = []
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            port = 8888
            try:
                from ops_config import load_config

                port = int(load_config().get("ui_port") or 8888)
            except Exception:
                pass
            base = f"http://{ip}:{port}"
            urls = [
                base + "/",
                base + "/checkin",
                base + "/instances",
                base + "/jobs",
                base + "/audit",
            ]
    except OSError:
        pass
    return urls


if __name__ == "__main__":
    print(json.dumps(checkin_payload(), indent=2)[:4000])
