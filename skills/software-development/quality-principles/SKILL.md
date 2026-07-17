---
name: quality-principles
description: Use for every PM, market research, roadmap executor, and CI autofix turn. Loads product-specific quality bars and per-repo PR lessons from the brain (PRINCIPLES + PR_QUALITY). Update the brain when you learn lasting lessons.
version: 1.0.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [quality, principles, pr, executor, pm, market, autofix]
    related_skills: [brain, dev-test-loop, roadmap, human-approval, auto-pr-fixer]
---

# Quality principles (generated from brain)

> **Do not hand-edit this file long-term.** Edit `$HERMES_HOME/brain/PRINCIPLES.md` and `PR_QUALITY.md`, then run `python sync_quality_skill.py` (also run from brain consolidate).

## How to use

1. `brain_read.py --sections PRINCIPLES,PR_QUALITY,PRODUCTS` (always before acting).
2. Follow the role section that matches this job (Executor / Product manager / Market research / CI autofix).
3. For code PRs, obey the repo section under PR_QUALITY.
4. After lasting lessons: `brain_write.py PR_QUALITY --append` and/or `brain_write.py PRINCIPLES --append`.
5. Re-run `sync_quality_skill.py` after brain edits.

---

# PRINCIPLES

## Executor (roadmap / `dev-test-loop`)

1. **Timebox 20–30 minutes.** Keep shipping agent-owned slices until the window is used.
2. **Decompose big/vague items** into prioritized roadmap children, then work the highest-priority child.
3. **One concern per PR.** Smallest change that meets acceptance for the current slice.
4. **Prove it.** Prefer failing test first; run the repo’s real verifier before PR.
5. **PR hygiene.** Clear title/body; label `hermes-exec`; enable auto-merge when safe; never force-push main.
6. **Read `PR_QUALITY` for that repo before coding.**
7. **Respect PRODUCTS / DECISIONS** constraints.
8. **HITL clarity.** ACTION vs APPROVAL with exact steps.
9. **Done means merged (or queued green), not “PR opened.”**
10. **Follow-ups** before exit (owner + priority); no busywork.
11. **Leave the trail better** — append lessons to `PR_QUALITY`.
12. No secrets in git/chat/Telegram.

## Product manager (roadmap)

1. Brain first before editing the roadmap.
2. Owner every item (`agent` | `human`); human items need `human_actions`.
3. Decompose discovery into concrete follow-on items.
4. HITL early for billing/secrets/prod.
5. No application code from PM cron.
6. Final Telegram response: `[SILENT]` unless HITL/failure.

## Market research

1. Prefer primary sources; notes that help PM create roadmap items.
2. Update MARKET + BUYERS; `[SILENT]` if nothing material changed.

## CI autofix

1. Real fixes only; max 1 open `hermes-autofix` per repo.
2. Skip release/prod/hotfix/status-page noise.
3. Read `PR_QUALITY` + PRODUCTS before patching.
4. Escalate secrets/permissions cleanly via human-approval.

## Daily ops review

1. Grade from Audit day scorecard + OPS_DESIGN.
2. Safe improvements only; keep cost ladder.
3. Always deliver the day report (never `[SILENT]` for this job).

## Audit loop (all agent crons)

1. Start: `ops_audit.py recent --job <id> -n 5` and `recent --status blocked -n 8`.
2. Finish: `ops_audit.py append` with structured flags when known.

---

# PR_QUALITY

Per-repo PR / CI quality memory. Add one section per product from your `ops-config.yaml`.

## example-app (`your-org/example-app`)

### Do
- Small PRs; run the project’s default verifier before opening a PR
- Label `hermes-exec` / `hermes-autofix`; link roadmap item or failing run

### Don't
- Force-push main
- Broad refactors in autofix PRs

### CI gotchas
- _(fill after first red CI)_

### Recent lessons
- _(append dated notes)_
