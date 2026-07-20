# Hermes Ops Design (source of truth)

**Read this periodically.** Packaged by [hermes-ops-kit](../README.md). Last reviewed: 2026-07-20 (item context notes + sentinel UNAVAILABLE).

| Quick links | Path |
|-------------|------|
| This doc | `~/.hermes/OPS_DESIGN.md` |
| Model cheat sheet | `~/.hermes/OPS_MODELS.md` |
| Shared brain | `$HERMES_HOME/brain/` |
| Cron registry | `$HERMES_HOME/cron/jobs.json` |
| Cron outputs | `$HERMES_HOME/cron/output/<job_id>/` |
| Roadmap SoT | `~/.hermes/roadmaps.json` |
| Roadmap / Jobs / Audit UI | `http://127.0.0.1:8888/` (`server.py`) |
| Audit UI | `http://127.0.0.1:8888/audit` |
| Day digest (latest) | `$HERMES_HOME/brain/DAILY_DIGEST_LATEST.md` |
| Ops audit trail | `$HERMES_HOME/brain/AUDIT.md` (+ `AUDIT.jsonl`, `AUDIT_YYYY-MM-DD.md`) |
| Ops changelog | `$HERMES_HOME/brain/OPS_CHANGELOG.md` |
| Daily reports log | `$HERMES_HOME/brain/DAILY_REPORTS.md` |
| Ops config | `$HERMES_HOME/ops-config.yaml` |
| GitHub bot setup | `~/.hermes/GITHUB_SERVICE_ACCOUNT.md` |

Hermes home for cron/scripts/skills: `$HERMES_HOME` (default `%LOCALAPPDATA%\hermes` on Windows). Mirror helpers also live under `~/.hermes/scripts/` — **cron must resolve scripts under `$HERMES_HOME/scripts/`**.

---

## Goals

1. Keep a shared **brain** that chat and cron both use (filesystem bus; cron skips MEMORY injection).
2. Watch CI on tracked branches → open real autofix PRs → monitor checks.
3. Maintain a roadmap with PM classification **agent vs human**, clear HITL.
4. Market research feeds the brain; PM updates roadmap from brain/state.
5. Executor runs a full **dev-test loop** with explicit ACTION / APPROVAL gates.
6. Cost-aware autonomy **C** (auto PRs / advance roadmap; Telegram only on failures, ambiguity, human gates — except the daily ops report, which always sends).
7. End of day: grade the stack, improve it safely, Telegram a concise day report.

---

## Autonomy & HITL

- **Autonomy C:** agents may open PRs and advance agent-owned roadmap items without asking.
- **Telegram is sparse:** failures / needs attention, human ACTION/APPROVAL (weekdays), and the **daily ops report**. Not routine “job ran”, PM briefs, or successful merges/PRs — those go to AUDIT + UI.
- Agent crons: final response is exactly `[SILENT]` after audit unless (a)/(HITL)/(daily report). No completion summaries in the final response. Quiet scripts use empty stdout on success.
- Human blocks must be exact: `blocked_reason` starts with `ACTION:` or `APPROVAL:`; numbered `human_actions`; formatter `human_block_format.py`.
- Never force-push main. No secrets in chat or brain files.

### Weekend policy

- Crons **run daily** (including weekends): CI/PM/executor/market + always-on scripts.
- **Avoid HITL on weekends:** no new Telegram ACTION/APPROVAL packets; prefix deferred gates with `WEEKEND-DEFER:`; continue other agent work.
- `human_queue_watch` tracks the queue but **does not reminder-ping** Sat/Sun (configured timezone).
- `pr-monitor` still **merges green** PRs; APPROVAL Telegram waits until weekday.
- Urgent exception: active security / data-loss risk.

### PR merge policy (roadmap executor + autofix)

| Labels | Checks | Behavior |
|--------|--------|----------|
| `hermes-exec` or `hermes-autofix` | green | **Auto-merge** squash (`gh pr merge --auto --squash --delete-branch`); `pr-monitor.py` every 30m also merges |
| + `hermes-needs-approval` or body `HERMES_NEEDS_APPROVAL` | green | **Hold** — Telegram APPROVAL ping; merge only after you reply `yes` |
| either | red | Telegram RED; no merge |
| either | pending | Silent |

Executor marks Done when merged (or auto-merge queued, checks not red). Prod/breaking/migration work must set the approval hold — ordinary roadmap PRs should not.

**GitHub identity:** prefer a dedicated bot via `HERMES_GH_TOKEN` (see `GITHUB_SERVICE_ACCOUNT.md`). Until set, ambient `gh` login is used.

---

## Model routing

See `OPS_MODELS.md`. Cost ladder: `no_agent` → local/cheap → mid → strongest coding model.

Configure concrete provider/model IDs in `ops-config.yaml` → `models:`. Configure Hermes `fallback_providers` so rate limits on the executor path failover instead of silent stalls.

| Tier | Use |
|------|-----|
| $0 scripts (`no_agent`) | Sentinel, PR monitor, brain consolidate, digest gather |
| Local / cheap | PM, market research, daily ops review, auxiliaries |
| Mid-tier coding | CI autofix first attempt |
| Strongest coding | Roadmap executor (primary); autofix escalate on repeat fail |

---

## Brain bus

Files under `$HERMES_HOME/brain/`:

| File | Role |
|------|------|
| `INDEX.md` | Pointers + roadmap snapshot |
| `PRODUCTS.md` | Product intent / status |
| `MARKET.md` | Market notes |
| `BUYERS.md` | Buyer / acquirer notes |
| `PIPELINES.md` | CI / pipeline health (+ local sentinel section) |
| `DECISIONS.md` | Durable decisions |
| `PRINCIPLES.md` | Role quality bars (executor / PM / market / autofix) |
| `PR_QUALITY.md` | Per-repo PR/CI living lessons |
| `DAILY_DIGEST_*.md` | Factual day digests (script) |
| `OPS_CHANGELOG.md` | Improvements applied by daily review |
| `DAILY_REPORTS.md` | Archive of Telegram day reports |

Helpers: `brain_read.py`, `brain_write.py`, `brain_consolidate.py`, `brain_paths.py`, **`ops_audit.py`**, **`sync_quality_skill.py`**. Skills: `brain`, **`quality-principles`**.

### Quality loop (PR + roles)

1. **SoT in brain:** `PRINCIPLES.md` (role bars) + `PR_QUALITY.md` (per-repo Do/Don’t/CI gotchas/lessons).
2. **Skill mirror:** `sync_quality_skill.py` regenerates `quality-principles` SKILL from those files (also on brain consolidate @ 06:00).
3. **Executor / autofix:** read PRINCIPLES + repo PR_QUALITY before PRs; append dated lessons after outcomes.
4. **PM / market / ops review:** follow their PRINCIPLES sections; ops review patches brain when the same miss repeats.

Edit brain files — not the generated skill — then sync.

### Ops audit trail (control plane)

`AUDIT.jsonl` is the ops SoT for **what ran and what blocked**. Brain stays product state; audit is the run ledger.

| File | Role |
|------|------|
| `AUDIT.jsonl` | Append-only machine log (one JSON object per event) |
| `AUDIT_YYYY-MM-DD.md` | Human-readable day log |
| `AUDIT.md` | Copy of today’s day log (easy open) |

**Event fields:** `job_id`, `name`, `status`, `summary`, `detail`, `artifacts`, plus optional `repo`, `pr_url`, `roadmap_item`, `human_gate`, `model`.

```bash
# Write
python "$HERMES_HOME/scripts/ops_audit.py" append \
  --job <job_id> --name "..." --status ok|error|partial|blocked|silent \
  --summary "one line" --detail "..." --artifact <url_or_path> \
  --repo owner/name --pr-url https://... --roadmap-item "..." \
  --human-gate "ACTION: ..." --model <id>

# Read before acting (agents)
python "$HERMES_HOME/scripts/ops_audit.py" recent --job <job_id> -n 5
python "$HERMES_HOME/scripts/ops_audit.py" recent --status blocked -n 8

# Evening scorecard (also embedded in ops_day_digest)
python "$HERMES_HOME/scripts/ops_audit.py" day-summary
```

**Write paths:**

1. **Script jobs** call `ops_audit.py` themselves.
2. **Agent jobs** are prompted to append (with structured flags) and to **read** `recent` / blocked first.
3. **`audit_ingest_cron.py`** (`g9auditingest` */10; also from digest) backfills forgotten agent runs as `[auto-ingest]` (dedupe: `brain/AUDIT_INGESTED.json`). Pulls repo/PR/gate from response text when present.

**Read paths:** Daily digest leads with **Audit day scorecard**; daily review grades from it; UI at http://127.0.0.1:8888/audit. Noisy watchdogs skip audit when nothing changed.

---

## Roadmap

- SoT: `~/.hermes/roadmaps.json`
- CLI: `roadmap_cli.py`; skill: `roadmap`
- Fields: `owner` (`agent`|`human`), `human_actions`, `blocked`, `blocked_reason` (`ACTION:` / `APPROVAL:`), **`notes`** (structured item context)
- UI on port **8888** (or `ui_port` in config): filter/sort + **Needs you** panel (reason + numbered steps + **release to agent**)
- **Item context:** agent-owned work needs structured `--notes` (Why / Scope / Acceptance / Context / Out of scope). Titles stay short; detail lives in notes. See roadmap skill.
- **Populate on escalate:** PM/executor/autofix must set owner=human, blocked=true, ACTION/APPROVAL reason, and 3–6 short `human_actions` (never empty)
- **Watch:** `human_queue_watch.py` (`g10humanq` */15) Telegram-reminds with exponential backoff (immediate → 30m → 1h → 2h → 4h → 8h → 24h) until released; one RESOLVED ping when cleared; state in `brain/HUMAN_QUEUE_STATE.json`
- Release in UI → `owner=agent` `blocked=false` → next executor resumes

---

## Skills (ops-critical)

| Skill | Purpose |
|-------|---------|
| `brain` | Read/write shared brain |
| `roadmap` | CRUD roadmap items (+ item context notes) |
| `dev-test-loop` | Executor implementation loop |
| `human-approval` | HITL ACTION/APPROVAL contract |
| `quality-principles` | Role + per-repo quality bars (generated from brain) |
| `ops-daily-review` | End-of-day grade + improve + report |
| `auto-pr-fixer`, `github-*`, `systematic-debugging`, `test-driven-development` | CI / exec support |

---

## Cron jobs (designed = kit templates)

Times use `timezone` from `ops-config.yaml` (default America/Chicago). Most jobs `deliver: telegram` but stay quiet unless material; consolidate/sync/audit-ingest use `deliver: local`.

| ID | Schedule | Mode | Expectation |
|----|----------|------|-------------|
| `a1brain0600` | 06:00 daily | `no_agent` `brain_consolidate.py` | Refresh INDEX; ok/silent |
| `41cb7755ae6d` | 07:00 daily | `no_agent` `project-sentinel.py` | Local project health → PIPELINES (`OK` / `FAIL` / `UNAVAILABLE`) |
| `026c0a4c82b7` | 08/12/16/20 daily | script `pipeline-scan.py` + agent | Wake only on failures; ≤1 `hermes-autofix` PR/repo |
| `b2prmon30m` | */30 | `no_agent` `pr-monitor.py` | Poll `hermes-autofix` + `hermes-exec`; merge-on-green; APPROVAL Telegram **weekdays only** |
| `c3pm0930` | 09:30 daily | agent | Brain-first PM; owner + HITL + item-context notes (weekend: prefer agent items, defer HITL Telegram) |
| `d4exec1014` | 10:00 & 14:00 daily | agent | ~20–30m timebox; enrich notes before coding; decompose; follow-ups; weekend: no new HITL Telegram |
| `e5market184` | 18:00 daily | agent | Market/buyers → brain; SILENT if no change |
| `f6ops2100` | 21:00 daily | script `ops_day_digest.py` + agent | Grade day; safe improvements; **always** Telegram report |
| `g7ui5m` | */5 | `no_agent` `roadmap_ui_watchdog.py` | Keep roadmap UI up |
| `g8sync0615` | 06:15 daily | `no_agent` `sync_hermes_mirrors.py` | Sync scripts/skills/docs HERMES_HOME ↔ `~/.hermes` |
| `g9auditingest` | */10 | `no_agent` `audit_ingest_cron.py` | Backfill agent cron outputs → AUDIT |
| `g10humanq` | */15 | `no_agent` `human_queue_watch.py` | Needs-you Telegram backoff (**suppressed Sat/Sun**); detect UI releases |

Repos for CI/PR monitor: from `ops-config.yaml` → `github.repos`. Local health checks: `projects:` (sentinel). Models: `models:`.

### Project sentinel — delivery contract

`no_agent` delivery:

- exit 0 + empty stdout → silent success
- exit 0 + stdout → deliver digest (HITL window / issues)
- exit ≠ 0 → cron marks job ERROR (“script failed”) even if health checks ran

So sentinel keeps **exit 0** when the script itself succeeded. Product failures and missing verifiers are reported via stdout + audit status (`error` / `partial`), not via non-zero exit. Missing tools → **`UNAVAILABLE`** (ops gap), not product **`FAIL`**. Prefer repo-local toolchains (venv / `node_modules`) so thin cron PATH does not false-fail.

### Daily ops review (`f6ops2100`) — detail

1. **Gather (script, $0):** `ops_day_digest.py` reads `jobs.json`, today’s `cron/output`, roadmap human queue, brain sizes → writes `DAILY_DIGEST_YYYY-MM-DD.md` + `DAILY_DIGEST_LATEST.md`, prints digest + `{"wakeAgent": true}` (always wakes).
2. **Review (agent):** skill `ops-daily-review` vs this doc’s expectations:
   - Jobs didn’t fail unexpectedly
   - Jobs did what was expected (incl. correct silence)
   - Safe improvements for goals + low cost
3. **Apply safe edits only:** prompt tightening, pin cheaper models, skill clarity, backup `jobs.json` before JSON edits. No deleting jobs, no raising all jobs to the strongest model, no disabling approvals, no prod force-merge.
4. **Persist:** append `OPS_CHANGELOG.md` + `DAILY_REPORTS.md`.
5. **Telegram (never silent):** concise Good / Bad / Human queue / Improvements / Cost / Tomorrow watch.

---

## Day pipeline (weekday mental model)

```
06:00  Brain consolidate
06:15  Sync mirrors
07:00  Project sentinel
08:00  CI scan (+ autofix if needed)     …also 12/16/20 (daily)
09:30  Product manager (daily; weekend defer HITL)
10:00  Roadmap executor                  …also 14:00 (daily; weekend defer HITL)
*/15   Human queue watch (Telegram backoff; quiet Sat/Sun)
*/30   PR monitor (merge-on-green; APPROVAL ping weekdays)
18:00  Market research (daily; SILENT if unchanged)
21:00  Daily ops review + Telegram report
```

---

## Known gaps / intentional omissions

| Item | Status |
|------|--------|
| Strongest model as daily default for PM/market/ops | Intentionally **not** — quota; escalate only |
| Roadmap UI autostart | Prefer `roadmap_ui_watchdog` + optional OS logon task; keep `roadmap.html` synced |
| Live proof of every agent path | Smoke lightly; daily review watches ongoing health |
| Market prompt paths | May use `~/.hermes/scripts/`; keep mirrors in sync with `$HERMES_HOME/scripts` |
| GitHub service account | Documented; set `HERMES_GH_TOKEN` for the bot path |
| Branch protection review bypass for bot | If rules require human review, green PRs Telegram APPROVAL until you comment `yes` / add `hermes-approved` |
| Extra cheap cloud tiers | Optional — wire only when the API key exists |

---

## How to re-audit

1. Open this file.
2. `hermes auth list` — expect your configured providers.
3. `hermes cron list` — jobs match the table; models match `ops-config.yaml`.
4. Skim latest `brain/DAILY_DIGEST_*.md` and `OPS_CHANGELOG.md`.
5. Confirm Telegram home channel matches allowlisted user id.
6. `python install/doctor.py` from the kit (or `$HERMES_HOME` after install).

When changing the stack: update **this doc**, `OPS_MODELS.md`, and `brain/DECISIONS.md` in the same change.
