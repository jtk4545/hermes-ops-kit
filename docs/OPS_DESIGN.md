# Hermes Ops Design (source of truth)

**Read this periodically.** Packaged by [hermes-ops-kit](../README.md).

| Quick links | Path |
|-------------|------|
| This doc | `~/.hermes/OPS_DESIGN.md` |
| Model cheat sheet | `~/.hermes/OPS_MODELS.md` |
| Shared brain | `$HERMES_HOME/brain/` |
| Cron registry | `$HERMES_HOME/cron/jobs.json` |
| Cron outputs | `$HERMES_HOME/cron/output/<job_id>/` |
| Roadmap SoT | `~/.hermes/roadmaps.json` |
| Roadmap / Jobs / Audit UI | `http://127.0.0.1:8888/` (`server.py`) |
| Ops config | `$HERMES_HOME/ops-config.yaml` |
| GitHub bot setup | `~/.hermes/GITHUB_SERVICE_ACCOUNT.md` |

Hermes home for cron/scripts/skills: `$HERMES_HOME` (default `%LOCALAPPDATA%\hermes` on Windows). Mirror helpers also live under `~/.hermes/scripts/` — **cron must resolve scripts under `$HERMES_HOME/scripts/`**.

---

## Goals

1. Keep a shared **brain** that chat and cron both use (filesystem bus).
2. Watch CI on tracked branches → open real autofix PRs → monitor checks.
3. Maintain a roadmap with PM classification **agent vs human**, clear HITL.
4. Market research feeds the brain; PM updates roadmap from brain/state.
5. Executor runs a full **dev-test loop** with explicit ACTION / APPROVAL gates.
6. Cost-aware autonomy **C** (auto PRs / advance roadmap; Telegram only on failures, ambiguity, human gates — except the daily ops report).
7. End of day: grade the stack, improve it safely, Telegram a concise day report.

---

## Autonomy & HITL

- **Autonomy C:** agents may open PRs and advance agent-owned roadmap items without asking.
- **Telegram is sparse:** failures / needs attention, human ACTION/APPROVAL (weekdays), and the **daily ops report**. Not routine “job ran”, PM briefs, or successful merges/PRs — those go to AUDIT + UI.
- Agent crons: final response is exactly `[SILENT]` after audit unless (a)/(HITL)/(daily report).
- Human blocks must be exact: `blocked_reason` starts with `ACTION:` or `APPROVAL:`; numbered `human_actions`; formatter `human_block_format.py`.
- Never force-push main. No secrets in chat or brain files.

### Weekend policy

- Crons **run daily** (including weekends).
- **Avoid HITL on weekends:** no new Telegram ACTION/APPROVAL packets; prefix deferred gates with `WEEKEND-DEFER:`.
- `human_queue_watch` does not reminder-ping Sat/Sun (configured timezone).
- `pr-monitor` still **merges green** PRs; APPROVAL Telegram waits until weekday.

### PR merge policy

| Labels | Checks | Behavior |
|--------|--------|----------|
| `hermes-exec` or `hermes-autofix` | green | Auto-merge squash |
| + `hermes-needs-approval` or body `HERMES_NEEDS_APPROVAL` | green | Hold — APPROVAL ping |
| either | red | Telegram RED; no merge |
| either | pending | Silent |

**GitHub identity:** prefer a dedicated bot via `HERMES_GH_TOKEN` (see `GITHUB_SERVICE_ACCOUNT.md`).

---

## Model routing

See `OPS_MODELS.md`. Cost ladder: `no_agent` → local/cheap → mid → strongest coding model.

Configure concrete provider/model IDs in `ops-config.yaml` → `models:`.

---

## Brain bus

Files under `$HERMES_HOME/brain/`:

| File | Role |
|------|------|
| `INDEX.md` | Pointers |
| `PRODUCTS.md` | Product intent / status |
| `MARKET.md` / `BUYERS.md` | Market notes |
| `PIPELINES.md` | CI / pipeline health |
| `DECISIONS.md` | Durable decisions |
| `PRINCIPLES.md` / `PR_QUALITY.md` | Quality bars + per-repo lessons |
| `AUDIT.jsonl` | Ops run ledger |

Helpers: `brain_read.py`, `brain_write.py`, `brain_consolidate.py`, `ops_audit.py`, `sync_quality_skill.py`.

### Ops audit trail

`AUDIT.jsonl` is the ops SoT for **what ran and what blocked**.

```bash
python "$HERMES_HOME/scripts/ops_audit.py" append \
  --job <job_id> --name "..." --status ok|error|partial|blocked|silent \
  --summary "one line"

python "$HERMES_HOME/scripts/ops_audit.py" recent --job <job_id> -n 5
python "$HERMES_HOME/scripts/ops_audit.py" recent --status blocked -n 8
python "$HERMES_HOME/scripts/ops_audit.py" day-summary
```

---

## Roadmap

- SoT: `~/.hermes/roadmaps.json`
- CLI: `roadmap_cli.py`; skill: `roadmap`
- Fields: `owner` (`agent`|`human`), `human_actions`, `blocked`, `blocked_reason` (`ACTION:` / `APPROVAL:`)
- UI: filter/sort + **Needs you** panel (reason + numbered steps + **release to agent**)
- Watch: `human_queue_watch.py` (`g10humanq`) Telegram-reminds with exponential backoff until released

---

## Cron jobs (designed = kit templates)

Times use `timezone` from `ops-config.yaml` (default America/Chicago).

| ID | Schedule | Mode | Expectation |
|----|----------|------|-------------|
| `a1brain0600` | 06:00 daily | `no_agent` | Refresh INDEX |
| `41cb7755ae6d` | 07:00 daily | `no_agent` | Local project health → PIPELINES |
| `026c0a4c82b7` | 08/12/16/20 | script + agent | Wake only on failures; ≤1 autofix PR/repo |
| `b2prmon30m` | */30 | `no_agent` | Merge-on-green; APPROVAL weekdays |
| `c3pm0930` | 09:30 daily | agent | Brain-first PM; owner + HITL |
| `d4exec1014` | 10:00 & 14:00 | agent | ~20–30m timebox; decompose; follow-ups |
| `e5market184` | 18:00 daily | agent | Market/buyers → brain; SILENT if no change |
| `f6ops2100` | 21:00 daily | script + agent | Grade day; **always** Telegram report |
| `g7ui5m` | */5 | `no_agent` | Keep UI up |
| `g8sync0615` | 06:15 daily | `no_agent` | Sync mirrors |
| `g9auditingest` | */10 | `no_agent` | Backfill AUDIT |
| `g10humanq` | */15 | `no_agent` | Needs-you backoff |

Repos for CI/PR monitor: from `ops-config.yaml` → `github.repos`.

---

## How to re-audit

1. Open this file.
2. `hermes auth list` — expect your configured providers.
3. `hermes cron list` — jobs match the table; models match `ops-config.yaml`.
4. Skim latest `brain/DAILY_DIGEST_*.md` and `OPS_CHANGELOG.md`.
5. Confirm Telegram home channel matches allowlisted user id.
6. `python install/doctor.py` from the kit (or `$HERMES_HOME` after install).
