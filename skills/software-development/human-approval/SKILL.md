---
name: human-approval
description: Use when the executor/PM needs a human action or approval. Formats clear Telegram requests with exact steps, materials, and what happens after the user responds. Populates the roadmap Needs you UI panel.
version: 1.1.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [hitl, telegram, approval, blocked, roadmap]
    related_skills: [roadmap, dev-test-loop, brain]
---

# Human action & approval requests

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
2. `--human-actions` is **3–6 short steps** (one verb each, `|`-separated). No novels.
3. Include URLs/paths in steps or notes when needed
4. Last step should mention releasing in the UI when the human is done
5. Never leave `human_actions` empty on a blocked item

Panel: `http://127.0.0.1:8888/` → **Needs you**

## Telegram packet

```bash
python "$HERMES_HOME/scripts/human_block_format.py" --blocked-only
```

Cron **`g10humanq`** (`human_queue_watch.py`, every 15m) also Telegram-reminds with **exponential backoff** (immediate → 30m → 1h → 2h → 4h → 8h → 24h) until the item is released. Prefer letting that watch nag; still send a full packet on first escalate.

### Good vs bad

Bad: “Need GCP access.”  
Good: `ACTION: Create SA ci-runner` + steps that name project, role, and secret name.

Bad: empty `human_actions`  
Good: numbered, copy-pasteable steps the UI can show.

## After the user resolves

**Preferred:** user clicks **I did this — release to agent** in the UI (clears block, `owner=agent`).

Or CLI:

```bash
python "$HERMES_HOME/scripts/roadmap_cli.py" edit -p <project> -i "<item>" \
  --owner agent --blocked false --blocked-reason ""
```

Then:

1. `human_queue_watch` detects resolve → one Telegram “RESOLVED”
2. Next executor run (weekdays 10:00 / 14:00) picks `owner=agent` `blocked=false`
3. Record outcome in `DECISIONS` when the agent resumes

### Approving a held PR (merge-on-green resume)

Any one of these within ~30 minutes is enough for `pr-monitor.py` to merge a green PR:

1. Comment **`yes`** (or `approved` / `LGTM`) on the PR itself  
2. Add label **`hermes-approved`**  
3. Remove label **`hermes-needs-approval`** (and leave no body hold marker)  
4. Submit an approving GitHub review  

Telegram-only “yes” without one of the above does **not** merge by itself.

## Weekends (Sat/Sun America/Chicago)

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
