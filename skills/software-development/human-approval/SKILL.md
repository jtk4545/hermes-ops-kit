---
name: human-approval
description: Use when the executor/PM needs a human action or approval. Formats clear Telegram requests with exact steps, materials, and what happens after the user responds. Populates the roadmap Needs you UI panel.
version: 1.2.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [hitl, telegram, approval, blocked, roadmap]
    related_skills: [roadmap, dev-test-loop, brain]
---

# Human action & approval requests

## Human high-ROI ritual (ops value)

The scarce resource is the user. Highest leverage (15–30 min/weekday), in order:

1. **Approve / release green bot PRs** (`hermes-exec` / `hermes-autofix`) stuck on review holds — agent minutes compound only after merge.
2. **Clear ACTION items** with exact steps (console work + Release).
3. **APPROVAL** yes/no on gates (prod, billing, branch protection).

Do **not** spend human time rewriting agent PRs or re-doing executor work. Vague “need help” packets are a skill failure — fix `human_actions` instead.

Telegram-only “yes” does **not** merge PRs — need PR comment/label/review (below).

Two kinds of human asks — keep them distinct:

| Kind | Meaning | User response |
|------|---------|----------------|
| **ACTION** | User must do something outside agent capability | Complete numbered steps, then **release** in UI (or reply “done”) |
| **APPROVAL** | Agent is paused on a decision | Reply `yes` / `no` / choose option A/B, then release if roadmap-gated |

## Populate the Needs you panel (required)

Every escalation **must** write the roadmap item so the UI panel is complete:

```bash
python "$HERMES_HOME/scripts/roadmap_cli.py" edit -p <project> -i "<item>" \
  --owner human --blocked true \
  --blocked-reason "ACTION: <one short sentence>" \
  --human-actions "Step one|Step two|Step three|Click Release to agent in UI"
```

Rules:

1. `--blocked-reason` starts with `ACTION:` or `APPROVAL:`
2. `--human-actions` is **3–8 steps** (one verb each, `|`-separated). Short UI lines — but **never vague**.
3. Include **exact URLs**, resource names, scopes, and **secret/env var names** Hermes will read
4. Include a **done-when** line (last step or notes): what “Release” means
5. Last step should mention releasing in the UI when the human is done
6. Never leave `human_actions` empty on a blocked item

Panel: `http://127.0.0.1:8888/` → **Needs you**  
**Check-in:** `http://127.0.0.1:8888/checkin` — open bot PRs + Needs you (when enabled)

## Telegram packet

```bash
python "$HERMES_HOME/scripts/human_block_format.py" --blocked-only
```

Cron **`g10humanq`** (`human_queue_watch.py`, every 15m) also Telegram-reminds with **exponential backoff** (immediate → 30m → 1h → 2h → 4h → 8h → 24h) until the item is released. Prefer letting that watch nag; still send a full packet on first escalate.

### Good vs bad

Bad: “Need cloud access.”  
Good: `ACTION: Create SA ci-runner` + steps that name project, role, and secret name.

Bad: empty `human_actions`  
Good: numbered, copy-pasteable steps the UI can show.

## Agent-first UI for developer consoles (user preference)

Do **not** default console app creation (OAuth clients, marketplace apps, developer portals) to `owner=human` “because secrets.” Prefer:

| Phase | owner | Agent does | Human does |
|-------|-------|------------|------------|
| Access model lock | agent | Research + DECISIONS | Only if product choice is ambiguous (APPROVAL options) |
| App create in portal | **agent** | Browser / computer-use: forms, scopes, redirect URIs | Login email/password/2FA; “logged in” session unlock |
| Secrets storage | human (short) | Record **secret names** + app id only | Paste values into your secret store (never Telegram/git) |

Hard stops (browser + computer-use):

- Never type passwords, 2FA codes, payment, or permission dialogs
- Headless Hermes browser ≠ user’s browser session — login wall → block with **ACTION: login session**, not “create the whole app yourself”
- Never paste client secrets into chat; only names (`EXAMPLE_CLIENT_ID`, …)

## After the user resolves

**Preferred:** user clicks **I did this — release to agent** in the UI (clears block, `owner=agent`).

Or CLI:

```bash
python "$HERMES_HOME/scripts/roadmap_cli.py" edit -p <project> -i "<item>" \
  --owner agent --blocked false --blocked-reason ""
```

Then:

1. `human_queue_watch` detects resolve → one Telegram “RESOLVED”
2. Next eligible executor picks it up: **day** `d4exec1014` at **09:00, 11:00, 13:00, 15:00**; **night** `d4execnight` every 30m **22:00–04:30** (Codex only; 429 stops immediately)
3. Record outcome in `DECISIONS` when the agent resumes

### Approving a held PR (merge-on-green resume)

`pr-monitor.py` (`b2prmon30m`, every 30m, $0) merges green `hermes-exec` / `hermes-autofix` unless held. Any one of these is enough:

1. Comment **`yes`** (or `approved` / `LGTM`) on the PR itself  
2. Add label **`hermes-approved`**  
3. Remove label **`hermes-needs-approval`** (and leave no body hold marker)  
4. Submit an approving GitHub review  

Telegram-only “yes” without one of the above does **not** merge by itself.

## Weekends (Sat/Sun in configured timezone)

Prefer **not** to page the human. If blocked: still write roadmap fields, prefix `blocked_reason` with `WEEKEND-DEFER:`, audit, continue other agent work — **skip** Telegram `human_block_format` unless security/data-loss urgent. Reminder cron stays quiet until Monday.

## On each agent run (PM / executor / autofix)

1. Read Needs you: `roadmap_cli.py show` + `ops_audit.py recent --status blocked -n 8`
2. If a prior block for your work is now `owner=agent` + `blocked=false` → **resume it**
3. If still blocked → do not re-implement; refresh steps if wrong; leave watch to Telegram
4. New blocks must populate the panel fields as above

## Completion criteria

- User can act without asking a clarifying question
- Needs you panel shows reason + steps
- Related materials (URLs/paths) are in the message or steps
- Roadmap `human_actions` matches what Telegram/UI show
