---
name: roadmap
description: Use when viewing or changing the multi-project roadmap (In Progress/Upcoming/Backlog/Done). Classify each task as owner=agent or owner=human; escalate blocked human work to Telegram with exact actions.
version: 1.1.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [roadmap, planning, products, human-in-the-loop]
    related_skills: [brain, human-approval, dev-test-loop]
---

# Roadmap

**Source of truth:** `{{HERMES_PROJECTS_ROOT}}\.hermes\roadmaps.json`  
**CLI:** `python {{HERMES_PROJECTS_ROOT}}\.hermes\scripts\roadmap_cli.py`  
**UI:** `python {{HERMES_PROJECTS_ROOT}}\.hermes\scripts\server.py` → http://127.0.0.1:8888/  
**Human queue formatter:** `python {{HERMES_PROJECTS_ROOT}}\.hermes\scripts\human_block_format.py`

## Owner classification (required)

| owner | Meaning |
|-------|---------|
| `agent` | Hermes/executor can do it (code, tests, PRs, local checks) |
| `human` | Needs the user (billing, prod credentials, legal, hardware, registrar DNS, App Store, bank, subjective product call) |

Fields on every item:

- `owner`: `agent` | `human`
- `human_actions`: list of **exact** steps the human must perform
- `blocked`: true when work cannot proceed without the human
- `blocked_reason`: one-line why

## CLI examples

```bash
python {{HERMES_PROJECTS_ROOT}}\.hermes\scripts\roadmap_cli.py show
python {{HERMES_HOME}}/scripts/roadmap_cli.py add -p example-app -i "Ship feature X" --phase Upcoming --priority 1 --owner agent --tags core
python {{HERMES_HOME}}/scripts/roadmap_cli.py add -p example-app -i "Enable billing" --phase Upcoming --priority 1 --owner human --blocked true --blocked-reason "Needs billing admin" --human-actions "Open billing console|Attach project|Reply done"
python {{HERMES_HOME}}/scripts/roadmap_cli.py edit -p example-app -i "Ship feature X" --owner human --blocked true --blocked-reason "Need prod secret" --human-actions "Create GitHub secret FOO|Paste value|Reply"
python {{HERMES_PROJECTS_ROOT}}\.hermes\scripts\human_block_format.py
```

## Telegram when human is needed

When you **create or refresh** a HITL gate (`owner=human` active or `blocked=true` needing a new ask):

1. Ensure `human_actions` lists concrete steps (not vague “fix credentials”).
2. Run `human_block_format.py` and put that **full text** as the final cron response (summary + context + numbered actions).
3. Do not implement human items.
4. Otherwise final response is exactly `[SILENT]` — no PM briefs or status reports. `g10humanq` reminds on open HITL with backoff.

## Process

1. Prefer CLI over hand-editing JSON.
2. PM classifies owner on create/edit; executor only runs `owner=agent` and `blocked=false` using skill `dev-test-loop`.
3. Executor may **decompose** large items into prioritized children (`add` + `--priority`) and must add **follow-ups** it discovers at end of a run.
4. Mid-loop human gates use skill `human-approval` (`ACTION:` vs `APPROVAL:` in `blocked_reason`).
5. Persist intent to brain (`PRODUCTS` / `DECISIONS`) when priorities change.

## Completion criteria

- Every new/changed item has `owner` set
- Human/blocked items have `human_actions`; new HITL asks deliver `human_block_format.py` output (else `[SILENT]`)
- Agent items are executable without human secrets
