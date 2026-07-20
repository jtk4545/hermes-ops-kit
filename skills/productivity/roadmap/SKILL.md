---
name: roadmap
description: Use when viewing or changing the multi-project roadmap (In Progress/Upcoming/Backlog/Done). Classify each task as owner=agent or owner=human; escalate blocked human work to Telegram with exact actions.
version: 1.2.0
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
- `notes`: **required context** for agent work (see below) — titles stay short; detail lives here
- `priority`, `date`, `tags`

## Item context (`--notes`) — required

Do **not** leave `notes` empty for agent-owned items. Use this structure (~800 chars max):

```text
Why: <pain / outcome — one sentence>
Scope: <modules/paths/APIs this touches>
Acceptance: <falsifiable done-when — tests, behavior, or PR outcome>
Context: <parent item, related PRs/issues, constraints, brain pointers>
Out of scope: <explicit non-goals for this slice>
```

Rules:

- Promoting to In Progress or decomposing children requires full notes first.
- PM backfills thin (empty/short) notes on In Progress + P1 Upcoming/Backlog each run.
- Executor must enrich notes before coding if `Acceptance:` is missing.
- On Done: append `Shipped: <PR url> — <one line>`.
- Human items still need Why + Context in notes; steps stay in `human_actions`.

## CLI examples

```bash
python {{HERMES_PROJECTS_ROOT}}\.hermes\scripts\roadmap_cli.py show
python {{HERMES_HOME}}/scripts/roadmap_cli.py add -p example-app -i "Ship feature X" --phase Upcoming --priority 1 --owner agent --tags core --notes "Why: Users cannot export. Scope: export/*.py. Acceptance: unit tests for CSV; smoke green. Context: parent reporting epic. Out of scope: PDF."
python {{HERMES_HOME}}/scripts/roadmap_cli.py add -p example-app -i "Enable billing" --phase Upcoming --priority 1 --owner human --blocked true --blocked-reason "ACTION: Needs billing admin" --human-actions "Open billing console|Attach project|Reply done" --notes "Why: Deploy blocked without billing. Scope: cloud project. Acceptance: billing account linked. Context: blocks feature X. Out of scope: budget alerts."
python {{HERMES_HOME}}/scripts/roadmap_cli.py edit -p example-app -i "Ship feature X" --notes "Why: … Scope: … Acceptance: … Context: … Out of scope: …"
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
3. Executor may **decompose** large items into prioritized children (`add` + `--priority` + full `--notes`) and must add **follow-ups** it discovers at end of a run.
4. Mid-loop human gates use skill `human-approval` (`ACTION:` vs `APPROVAL:` in `blocked_reason`).
5. Persist intent to brain (`PRODUCTS` / `DECISIONS`) when priorities change.

## Completion criteria

- Every new/changed item has `owner` set
- Agent items have structured `notes` (Why / Scope / Acceptance / Context / Out of scope)
- Human/blocked items have `human_actions`; new HITL asks deliver `human_block_format.py` output (else `[SILENT]`)
- Agent items are executable without human secrets
