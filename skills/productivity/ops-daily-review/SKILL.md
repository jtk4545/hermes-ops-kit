---
name: ops-daily-review
description: Use for the end-of-day Hermes ops review cron. Grades today's jobs from AUDIT.jsonl scorecard vs OPS_DESIGN, applies safe cost/reliability improvements, writes changelog, and delivers a concise Telegram day report.
version: 1.2.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [ops, review, cron, cost, telegram, audit]
    related_skills: [brain, roadmap, human-approval, dev-test-loop, quality-principles, market-research]
---

# Daily ops review

## Inputs (required order)

1. Read design: `~/.hermes/OPS_DESIGN.md` (+ `OPS_MODELS.md` for model table)
2. Read digest (script-injected and/or):  
   `python "$HERMES_HOME/scripts/ops_day_digest.py"`  
   also `$HERMES_HOME/brain/DAILY_DIGEST_LATEST.md`
3. **Primary grade source:** the digest’s **Audit day scorecard** (from `AUDIT.jsonl`).  
   Or: `python "$HERMES_HOME/scripts/ops_audit.py" day-summary`
4. Secondary: registry section, `$HERMES_HOME/brain/PIPELINES.md`, `human_block_format.py`, flagged `$HERMES_HOME/cron/output/` only when scorecard is thin

Before finishing, append your own audit event via `ops_audit.py` (status ok/partial/error) summarizing grades + improvements.

## Grade each job

Prefer audit events over raw cron dumps:

| Check | Pass means |
|-------|------------|
| Audited when expected | Core job that fired has ≥1 audit event today (script or auto-ingest) |
| No failure | Latest status `ok`/`silent`/`partial` as appropriate; not unexplained `error`. **Caveat:** `no_agent` `last_status=error` often means **exit≠0**, not product red. |
| Blocked actionable | `blocked` events carry clear `human_gate` (ACTION:/APPROVAL:) or summary |
| Delivery | Jobs that should notify have no Telegram “Chat not found” / timeout. **Night executor invariant:** `d4execnight` must be `deliver=local` and expose no messaging toolset; results belong in audit/UI only. |
| Expectation | Matches OPS_DESIGN row (brain-first, owner classification, HITL clarity, etc.) |
| Cost | Cheapest viable tier; Grok weekly burn watched (do not lengthen day Grok) |
| Routing | Match the latest user-directed registry/DECISIONS state; dual-quota hard stop; $0 scripts never removed |

### Routing recency guard (mandatory before any schedule/model edit)

1. Inspect today's `AUDIT.jsonl`, `OPS_CHANGELOG.md`, `DECISIONS.md`, and the newest `jobs.json.backup-*` before labeling a difference as drift.
2. A same-day user-directed or operator-applied routing change is authoritative even when OPS_DESIGN, this skill, or an older reference still shows the prior topology. Update stale docs to the live decision—never normalize the registry backward.
3. If provenance is ambiguous, make **no routing change**; report the mismatch for human confirmation. Daily review may not remove providers, reduce/add slots, or rewrite schedules solely because an older canonical table disagrees.
4. When a routing change is confirmed, update registry, prompts, OPS_DESIGN, OPS_MODELS, DECISIONS, and this skill atomically.

### Current day / night model ladder (configured timezone)

| Tier | Jobs / use |
|------|------------|
| `no_agent` scripts | PR monitor, human queue, audit, brain, optional GCP, UI watchdog — **never throttle** |
| Bonsai | PM, market, daily ops review |
| Day Grok (`xai-oauth` / `grok-4.5`) | `d4exec1014` **09:00, 11:00, 13:00, 15:00** · **20–30m**; fallback **Composer 2.5 → Codex Sol** for in-flight slice only |
| CI autofix Codex Sol | `026c0a4c82b7` **09:30 + 15:30** — Sol primary; one Grok try only if Codex 429 mid-fix |
| Night Codex Sol | `d4execnight` every 30m **22:00–04:30** — empty fallback; **`deliver=local`, never Telegram**; stop on 429/auth/quota |

**Dual-quota HARD STOP:** if Grok **and** Codex exhausted/429 → coding jobs stop; audit `QUOTA:…`; one short Telegram line (notify window); no Copilot/Bonsai thrash.

## Allowed improvements (safe)

You **may** apply these without asking:

- Tighten cron prompts for `[SILENT]` / brain_read / audit recent+append / HITL wording
- Pin `provider`/`model` per day/night ladder; keep PM/market/ops-review on bonsai
- Fix script path typos; restore **QUOTA HARD STOP** wording if stripped from coding jobs
- Update skill text (dev-test-loop, human-approval, roadmap, market-research, auto-pr-fixer)
- Append `$HERMES_HOME/brain/OPS_CHANGELOG.md` and `$HERMES_HOME/brain/DAILY_REPORTS.md`
- Refresh `OPS_DESIGN.md` / `OPS_MODELS.md` when routing changes
- **Cron skill vs toolset mistakes** — toolset names must not sit under `skills` (classic: `web`). See `market-research`
- Restore `d4execnight` to `deliver=local` and remove messaging toolsets if either invariant drifts (safe reliability repair; do not send a test Telegram)

You **must not** without Telegram APPROVAL ask:

- Delete cron jobs or disable $0 keep-alives
- Collapse night Codex executor into day Grok without DECISIONS note
- **Lengthen day Grok timeboxes** or add extra Grok exec/autofix slots without DECISIONS
- Re-enable Copilot/Bonsai as coding fallbacks when Grok+Codex are dead
- Raise everything to Codex/Sol “for quality”
- Disable approvals / set `approvals.mode: off`
- Force-merge prod or change git remotes
- Put secrets in files or chat

When editing `$HERMES_HOME/cron/jobs.json`: read → timestamped backup → patch carefully → validate JSON.

## Telegram delivery (hard — whole fleet)

**Policy:** Mon–Fri **notify_window** (default 09:00–17:00) HITL/alerts only + **`f6ops2100` ~21:00** day report.  
All other jobs: work + brain/AUDIT OK; user-facing output **`[SILENT]`** or empty stdout.

- Human ritual UI: http://127.0.0.1:8888/checkin — open bot PRs + Needs you (when `features.checkin_ui`)
- **Night executor is stronger than `[SILENT]`:** `d4execnight` must have cron `deliver=local` and no messaging toolset
- **Do not** silence `f6ops2100`

## Telegram report shape (always deliver — never [SILENT])

```
OPS DAY REPORT — YYYY-MM-DD

Good:
- ...

Bad / risks:
- ... (or "none")

Human queue:
- ... (blocked audits + roadmap; or "none")

Improvements applied:
- ... (or "none")

Cost notes:
- ...

Tomorrow watch:
- ...
```

Keep it concise (roughly 15–30 lines). Link job ids when relevant.

### Report attribution guard

- Put something under **Improvements applied** only when this Daily Ops Review actually changed it.
- Same-day user/operator changes belong under **Good/current state**, not as review-authored improvements.
- If attribution is uncertain, say “observed today; author/run unverified” or omit it.

## Completion criteria

- Graded from Audit day scorecard + OPS_DESIGN
- Verified `d4execnight` (if present) remains `deliver=local` with no messaging toolset
- Safe improvements applied or explicitly skipped with reason
- Changelog + daily report written under `brain/`
- Full Telegram day report delivered (not silent)
