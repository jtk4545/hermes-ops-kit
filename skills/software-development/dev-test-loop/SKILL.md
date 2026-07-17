---
name: dev-test-loop
description: Use when executing a roadmap item end-to-end (implement, test, PR, CI). Enforces agent vs human gates, clear Telegram approvals, and quality principles for the Hermes ops executor.
version: 1.2.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [executor, testing, pr, hitl, roadmap, ci]
    related_skills:
      - roadmap
      - brain
      - human-approval
      - test-driven-development
      - systematic-debugging
      - github-pr-workflow
      - requesting-code-review
---

# Dev-test loop (roadmap executor)

Use this skill for every roadmap execution turn. Goal: ship verified progress in a **20–30 minute** window — or stop cleanly with a **clear human request**.

## Before coding

0. Load skill **`quality-principles`** (or `brain_read.py --sections PRINCIPLES,PR_QUALITY,PRODUCTS`) — follow Executor principles and the target repo’s PR_QUALITY section.
1. `brain_read.py --sections PRODUCTS,DECISIONS,PIPELINES,PRINCIPLES,PR_QUALITY`
2. `roadmap_cli.py show` — pick highest-priority **In Progress** item with `owner=agent` and `blocked=false`
3. **Decompose if needed:** if the item is too large/vague for one focused PR, split into 2–6 concrete children via `roadmap_cli.py add` with `--priority` + `--owner`, put the first child In Progress, then work that child. Note the parent in `--notes`.
4. Load project context: repo README / AGENTS.md / existing tests
5. Restate acceptance criteria in one short checklist (what “done” means)

If the item is `owner=human` or already `blocked=true`: do **not** code that item. Run `human_block_format.py` and deliver that to Telegram — then continue another unblocked agent item if time remains.

## Timebox (non-negotiable)

- Target **~20–30 minutes** of useful work per executor cron fire.
- **Do not** stop after one tiny item if time remains and more `owner=agent` `blocked=false` work exists.
- After finishing / queuing a PR / cleanly blocking an item: pick the next highest-priority agent item and continue until the window is used or the queue is empty.
- Still: each PR stays **one concern** (no drive-by refactors across unrelated work).

## Loop (tight)

```
understand → (decompose?) → smallest change → test → fix → PR → watch checks → merge-on-green or HITL
→ next item while time remains → follow-ups on roadmap
```

### Principles (non-negotiable)

1. **Timebox 20–30m; multiple slices OK.** Prefer finishing shippable slices over half-finishing many.
2. **Tests prove the change.** Prefer failing test first for new behavior/bugs (`test-driven-development`). Match the repo’s existing test runner (pytest, go test, tsc, gradle, etc.).
3. **Small PRs.** One concern per PR; clear title/body; label `hermes-exec`.
4. **Never force-push `main`/`trunk`.** Never skip hooks unless the user explicitly asks.
5. **No secrets in commits, logs, or Telegram.**
6. **Respect PRODUCTS/DECISIONS constraints** (do-not-touch areas, flaky tests).
7. **US-hosted tooling only** for model calls; local tools are fine.
8. **Follow-ups before exit.** Add real next work to the roadmap (priority + owner); skip only if nothing meaningful remains.

### Project test cheatsheet

Configure per-product verify commands in `ops-config.yaml` → `projects.*.checks` (used by project-sentinel). For the executor, run the repo’s real test/lint entrypoint before opening a PR. Example:

| Project | Default verify |
|---------|----------------|
| example-app | whatever your repo uses (`pytest`, `go test`, `npm test`, …) |

## Human steps & approvals (must be crystal clear)

Stop and escalate when you hit any gate below. Use skill `human-approval`.

| Gate | When | What to ask for |
|------|------|-----------------|
| **Action** | You cannot proceed without the user doing something outside the repo | Exact numbered steps (`human_actions`) |
| **Approval** | Choice is irreversible, product-ambiguous, or policy-sensitive | Explicit Yes/No (or A/B) with recommendation |
| **Secret** | Need API keys, prod creds, billing, DNS at registrar | Where to create + where to paste (never ask them to paste secrets into chat if a secret store exists — point them there) |
| **Prod/release** | Deploy to prod, merge with prod impact, data migration | Approval + rollback note |
| **Breaking API** | External clients would break | Approval with blast radius |

### Escalation checklist (every HITL message)

1. Mark roadmap item: `--owner human` (if needed) `--blocked true --blocked-reason "..." --human-actions "step1|step2"`
2. Run `human_block_format.py --blocked-only` (or full queue)
3. Telegram delivery **must include** that formatter output verbatim
4. Append one line to `DECISIONS.md` via `brain_write.py`
5. Stop work on that item (do not half-implement past the gate)

**Never** send vague asks like “need credentials” or “please approve.” Always: summary → why blocked → exact actions or Yes/No → links/paths → what you will do after.

## After implementation

1. Open PR with label **`hermes-exec`**; link roadmap item name in body. Prefer bot identity via `HERMES_GH_TOKEN` (see `{{HERMES_PROJECTS_ROOT}}\.hermes\GITHUB_SERVICE_ACCOUNT.md`).
2. **Merge policy (default: auto when green):**
   - **Safe / no approval gate:** after opening PR, run  
     `gh pr merge <n> --repo <owner/repo> --auto --squash --delete-branch`  
     Cron `pr-monitor.py` also merges green `hermes-exec` / `hermes-autofix` PRs every 30m.
   - **Needs your approval** (prod risk, breaking API, migration, spend, ambiguous product call):  
     - add label **`hermes-needs-approval`**  
     - put `HERMES_NEEDS_APPROVAL` in the PR body  
     - mark roadmap `--blocked true --blocked-reason "APPROVAL: merge PR #N ..."` + `human_actions`  
     - Telegram via `human_block_format.py` — **do not merge** until user replies `yes`
3. `brain_write.py PIPELINES --append` with PR URL + merge intent (`auto` or `awaiting-approval`)
4. If checks fail: one fix cycle (`systematic-debugging`); if still red → HITL with failing job URL + exact ask
5. Move roadmap item to Done only when merged (or acceptance met and merge queued) — not merely when PR opened; `brain_write.py PRODUCTS --append` (3–5 lines)
6. **Quality loop:** append a dated lesson under that repo in `PR_QUALITY.md` (`brain_write.py PR_QUALITY --append`). If the lesson is cross-product, append under PRINCIPLES → Executor. Then `python .../sync_quality_skill.py`.

## Follow-ups (end of run)

Before finishing, scan what this work unlocked or revealed. Add concrete items with `roadmap_cli.py add` (`--owner`, `--priority`, phase Upcoming/Backlog). No busywork.

## Completion criteria

- Used the ~20–30m window productively (or queue empty / HITL-only)
- Large items were decomposed onto the roadmap with priorities when needed
- Follow-ups added when real next work exists
- Either: PR(s) open with checks watched + auto-merge enabled (safe) **or** approval Telegram sent (risky) + brain/roadmap updated  
- Or: blocked item with Telegram human packet (formatter output) and no silent stall  
- Never: `[SILENT]` while a **new** human/approval ask must be delivered (weekday HITL packet)  
- Routine successful work (including merged PRs) → final response exactly `[SILENT]` after audit — no completion write-up on Telegram
- Never: merge a `hermes-needs-approval` PR without an explicit user `yes`
- Quality: PRINCIPLES/PR_QUALITY were read; lesson written when something lasting was learned
