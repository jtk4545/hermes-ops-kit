---
name: ops-daily-review
description: Use for the end-of-day Hermes ops review cron. Grades today's jobs from AUDIT.jsonl scorecard vs OPS_DESIGN, applies safe cost/reliability improvements, writes changelog, and delivers a concise Telegram day report.
version: 1.1.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [ops, review, cron, cost, telegram, audit]
    related_skills: [brain, roadmap, human-approval, dev-test-loop, quality-principles]
---

# Daily ops review

## Inputs (required order)

1. Read design: `~/.hermes/OPS_DESIGN.md`
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
| No failure | Latest status `ok`/`silent`/`partial` as appropriate; not unexplained `error` |
| Blocked actionable | `blocked` events carry clear `human_gate` (ACTION:/APPROVAL:) or summary |
| Delivery | No Telegram “Chat not found” / timeout on runs that should notify |
| Expectation | Matches OPS_DESIGN row (brain-first, owner classification, HITL clarity, etc.) |
| Cost | Cheapest viable tier used (no_agent > local/cheap > Grok 4.5 > Codex failover) |

## Allowed improvements (safe)

You **may** apply these without asking:

- Tighten cron prompts for `[SILENT]` / brain_read / audit recent+append / HITL wording
- Pin `provider`/`model` downward for cost (e.g. keep PM/market on bonsai; keep coding on `xai-oauth` / `grok-4.5`)
- Fix script path typos in prompts
- Update skill text for clarity (dev-test-loop, human-approval, roadmap)
- Append `$HERMES_HOME/brain/OPS_CHANGELOG.md` and `$HERMES_HOME/brain/DAILY_REPORTS.md`
- Refresh `OPS_DESIGN.md` “Known gaps” section if still accurate

You **must not** without Telegram APPROVAL ask:

- Delete cron jobs
- Raise all jobs to Grok/Codex (keep PM/market/ops on local/cheap)
- Disable approvals / set `approvals.mode: off`
- Force-merge prod or change git remotes
- Put secrets in files or chat

When editing `$HERMES_HOME/cron/jobs.json`: read → backup to `$HERMES_HOME/cron/jobs.backup.json` → patch carefully → validate JSON.

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

## Completion criteria

- Graded from Audit day scorecard + OPS_DESIGN
- Safe improvements applied or explicitly skipped with reason
- Changelog + daily report written under `brain\`
- Full Telegram day report delivered (not silent)
