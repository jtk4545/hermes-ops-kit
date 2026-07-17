# PRINCIPLES

Role quality bars. Edit this file; run `sync_quality_skill.py` to regenerate the skill.

## Executor
- Smallest shippable slice; tests before PR
- Labels: `hermes-exec`; auto-merge when safe
- HITL: `ACTION:` / `APPROVAL:` with numbered human_actions

## Product manager
- Every item has owner=agent or owner=human
- Human items always have human_actions
- No application code from PM cron

## Market research
- Prefer primary sources; US-relevant notes
- Persist to MARKET/BUYERS; silent if unchanged

## Autofix
- Max 1 open hermes-autofix PR per repo
- Real code fix linked to failing run
