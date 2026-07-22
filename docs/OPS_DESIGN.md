# Hermes Ops Design (source of truth)

**Read this periodically.** Packaged by [hermes-ops-kit](../README.md). Last reviewed: 2026-07-22 (portable day/night ladder + advanced topology).

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
| Check-in ritual | `http://127.0.0.1:8888/checkin` |
| Day digest (latest) | `$HERMES_HOME/brain/DAILY_DIGEST_LATEST.md` |
| Ops audit trail | `$HERMES_HOME/brain/AUDIT.md` (+ `AUDIT.jsonl`, `AUDIT_YYYY-MM-DD.md`) |
| Ops changelog | `$HERMES_HOME/brain/OPS_CHANGELOG.md` |
| Daily reports log | `$HERMES_HOME/brain/DAILY_REPORTS.md` |
| Ops config | `$HERMES_HOME/ops-config.yaml` |
| GitHub bot setup | `~/.hermes/GITHUB_SERVICE_ACCOUNT.md` |

Hermes home for cron/scripts/skills: `$HERMES_HOME`  
(defaults: Windows `%LOCALAPPDATA%/hermes`; Linux/macOS `$XDG_DATA_HOME/hermes` or `~/.local/share/hermes`).  
Mirror helpers also live under `~/.hermes/scripts/` — **cron must resolve scripts under `$HERMES_HOME/scripts/`**.

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
- **Telegram is sparse:** failures / needs attention (PR monitor: **Mon–Fri notify_window only**, default 09:00–17:00), human ACTION/APPROVAL (weekdays), and the **daily ops report**. Not routine “job ran”, PM briefs, or successful merges/PRs — those go to AUDIT + UI.
- **Notify window** is configurable in `ops-config.yaml` → `notify_window` (weekdays + start/end + `always_allow_jobs`).
- Agent crons: final response is exactly `[SILENT]` after audit unless (a)/(HITL)/(daily report). No completion summaries in the final response. Quiet scripts use empty stdout on success.
- Human blocks must be exact: `blocked_reason` starts with `ACTION:` or `APPROVAL:`; numbered `human_actions`; formatter `human_block_format.py`.
- Never force-push main. No secrets in chat or brain files.

### Weekend policy

- Crons **run daily** (including weekends): CI/PM/executor/market + always-on scripts.
- **Avoid HITL on weekends:** no new Telegram ACTION/APPROVAL packets; prefix deferred gates with `WEEKEND-DEFER:`; continue other agent work.
- `human_queue_watch` tracks the queue but **does not reminder-ping** Sat/Sun (configured timezone).
- `pr-monitor` still **merges green** PRs 24/7; **all** PR-monitor Telegram (APPROVAL / RED / merge-fail) only Mon–Fri within notify_window.
- Urgent exception: active security / data-loss risk.

### PR merge policy (roadmap executor + autofix)

| Labels | Checks | Behavior |
|--------|--------|----------|
| `hermes-exec` or `hermes-autofix` | green | **Auto-merge** squash (`gh pr merge --auto --squash --delete-branch`); `pr-monitor.py` every 30m also merges |
| + `hermes-needs-approval` or body `HERMES_NEEDS_APPROVAL` | green | **Hold** — Telegram APPROVAL ping only Mon–Fri notify_window; merge only after you reply `yes` |
| either | red | Telegram RED only Mon–Fri notify_window; no merge |
| either | pending | Silent |

Executor marks Done when merged (or auto-merge queued, checks not red). Prod/breaking/migration work must set the approval hold — ordinary roadmap PRs should not.

**GitHub identity:** prefer a dedicated bot via `HERMES_GH_TOKEN` (see `GITHUB_SERVICE_ACCOUNT.md`). Until set, ambient `gh` login is used.

**Model attribution:** executor/autofix create PRs through `gh_ops.py create-pr`, which adds `model:<model-id>` and a `Hermes-Model` footer while preserving `hermes-exec` / `hermes-autofix`.

---

## Model routing (day / night ladder)

See `OPS_MODELS.md`. Cost ladder: `no_agent` → Bonsai → day Grok → Codex Sol (CI + night).

Configure concrete provider/model IDs in `ops-config.yaml` → `models:`.

| Tier | Provider / model (defaults) | Use |
|------|-----------------------------|-----|
| $0 scripts | `no_agent` | Sentinel, PR monitor, brain consolidate, digest gather, optional GCP scan |
| Local | `bonsai-local` / `bonsai-27b` | PM, market research, daily ops review |
| Grok 4.5 | `xai-oauth` / `grok-4.5` | **Day** roadmap executor, evening UI live |
| Composer 2.5 | `xai-oauth` / `grok-composer-2.5-fast` | First fallback for a day executor's in-flight slice only |
| Codex Sol | `openai-codex` / `gpt-5.6-sol` | CI autofix primary; **night** roadmap executor; final day fallback for in-flight slice only |

**Dual-quota HARD STOP:** if Grok **and** Codex are both exhausted/unavailable → coding jobs **STOP**. Audit `QUOTA: …` and one short Telegram line (notify window). No Copilot/Bonsai coding thrash. Scripts + Bonsai PM/market/ops-review still run.

**Day Grok / night Codex (template defaults):**

| Job | Schedule | Model |
|-----|----------|-------|
| `d4exec1014` day executor | 09:00, 11:00, 13:00, 15:00 | Grok 4.5 → Composer 2.5 → Codex Sol · 20–30m |
| `d4execnight` night executor | every 30m, 22:00–04:30 | Codex Sol only; empty fallback; **`deliver=local`** |
| CI autofix | 09:30, 15:30 | Codex Sol primary; one Grok try if Codex exhausts mid-fix |
| UI live (optional) | 21:00 | Grok 4.5 |

Night executor delivery is permanently **local only**: no Telegram and no messaging toolset. Night outcomes go to AUDIT/UI for the next daytime review.

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
2. **Both roadmap executors** (`d4exec1014`, `d4execnight`) append a structured event before every exit, including `[SILENT]`, blocked, quota, partial, and error outcomes.
3. **`audit_ingest_cron.py`** (`g9auditingest` */10; also from digest) backfills forgotten agent runs as `[auto-ingest]` / `[registry-reconcile]` (dedupe: `brain/AUDIT_INGESTED.json`).

**Read paths:** Daily digest leads with **Audit day scorecard**; daily review grades from it; UI at http://127.0.0.1:8888/audit. Noisy watchdogs skip audit when nothing changed.

---

## Roadmap

- SoT: `~/.hermes/roadmaps.json`
- CLI: `roadmap_cli.py`; skill: `roadmap`
- Fields: `owner` (`agent`|`human`), `human_actions`, `blocked`, `blocked_reason` (`ACTION:` / `APPROVAL:`), **`notes`** (structured item context), stable `id`, timestamps, `activity`, and typed `related_items`
- UI on port **8888** (or `ui_port` in config): filter/sort + **Needs you** panel (reason + numbered steps + **release to agent**)
- **Check-in:** `http://127.0.0.1:8888/checkin` — human ritual surface (open bot PRs + Needs you). Optional; enable via `features.checkin_ui`.
- **Item context:** agent-owned work needs structured `--notes` (Why / Scope / Acceptance / Context / Out of scope). Titles stay short; detail lives in notes. See roadmap skill.
- **History/relationships:** CLI and UI writes preserve immutable IDs and append activity; use `roadmap_cli.py log` and `relate` for progress and dependencies.
- **Populate on escalate:** PM/executor/autofix must set owner=human, blocked=true, ACTION/APPROVAL reason, and 3–6 short `human_actions` (never empty)
- **Watch:** `human_queue_watch.py` (`g10humanq` */15) Telegram-reminds with exponential backoff (immediate → 30m → 1h → 2h → 4h → 8h → 24h) until released; one RESOLVED ping when cleared; state in `brain/HUMAN_QUEUE_STATE.json`
- Release in UI → `owner=agent` `blocked=false` → next eligible executor resumes (day or night)

---

## Skills (ops-critical)

| Skill | Purpose |
|-------|---------|
| `brain` | Read/write shared brain |
| `roadmap` | CRUD roadmap items (+ item context notes) |
| `market-research` | Daily market/buyer scan → brain |
| `dev-test-loop` | Executor implementation loop |
| `human-approval` | HITL ACTION/APPROVAL contract |
| `quality-principles` | Role + per-repo quality bars (generated from brain) |
| `ops-daily-review` | End-of-day grade + improve + report |
| `auto-pr-fixer`, `github-*`, `systematic-debugging`, `test-driven-development` | CI / exec support |

**Skills vs toolsets:** cron `skills` lists skill names only. Web search is the **`web` toolset** (`web_search` / `web_extract`) — never a skill named `web`. Market job: skills `market-research`, `brain`, `quality-principles` + toolsets `web`, `terminal`, `file`.

---

## Cron jobs (designed = kit templates)

Times use `timezone` from `ops-config.yaml` (default America/Chicago). Most jobs `deliver: telegram` but stay quiet unless material; consolidate/sync/audit-ingest/night executor use `deliver: local`.

### Core topology

| ID | Schedule | Mode | Model | Expectation |
|----|----------|------|-------|-------------|
| `a1brain0600` | 06:00 daily | `no_agent` `brain_consolidate.py` | — | Refresh INDEX; ok/silent |
| `41cb7755ae6d` | 07:00 daily | `no_agent` `project-sentinel.py` | — | Local project health → PIPELINES |
| `026c0a4c82b7` | 09:30, 15:30 daily | script `pipeline-scan.py` + agent | Codex Sol | Wake only on failures; ≤1 `hermes-autofix` PR/repo |
| `b2prmon30m` | */30 | `no_agent` `pr-monitor.py` | — | Merge-on-green 24/7; Telegram Mon–Fri notify_window only |
| `c3pm0930` | 09:30 daily | agent | Bonsai | Brain-first PM; owner + HITL (weekend: defer HITL Telegram) |
| `d4exec1014` | 09:00, 11:00, 13:00, 15:00 daily | agent | Grok 4.5 | ~20–30m; decompose; follow-ups; weekend: no new HITL Telegram |
| `e5market184` | 18:00 daily | agent | Bonsai | Market/buyers → brain; SILENT if no change |
| `f6ops2100` | 21:00 daily | script `ops_day_digest.py` + agent | Bonsai | Grade day; safe improvements; **always** Telegram report |
| `g7ui5m` | */5 | `no_agent` `roadmap_ui_watchdog.py` | — | Keep roadmap UI up |
| `g8sync0615` | 06:15 daily | `no_agent` `sync_hermes_mirrors.py` | — | Sync HERMES_HOME ↔ `~/.hermes` |
| `g9auditingest` | */10 | `no_agent` `audit_ingest_cron.py` | — | Backfill agent cron outputs → AUDIT |
| `g10humanq` | */15 | `no_agent` `human_queue_watch.py` | — | Needs-you Telegram backoff (**suppressed Sat/Sun**) |

### Optional advanced topology

Present in `jobs.template.json`; enable via `features:` in config and keep/disable in the live registry. Requires corresponding scripts/credentials.

| ID | Schedule | Mode | Model | Notes |
|----|----------|------|-------|-------|
| `d4execnight` | every 30m, 22:00–04:30 | agent | Codex Sol | **`deliver=local`**; empty fallback; quota hard stop; no Telegram |
| `h11uilive23` | 21:00 daily | script `ui-live-scan.py` + agent | Grok 4.5 | Wake on UI/live failures; ≤1 autofix PR/repo |
| `h12gcloud0730` | 07:30 daily | `no_agent` `gcloud-ops-scan.py` | — | Read-only cloud health/cost → PIPELINES; Telegram on issues; **no autofix wake** |

Repos for CI/PR monitor: from `ops-config.yaml` → `github.repos`. Local health checks: `projects:`. Models: `models:`. Feature flags: `features:`.

### Project sentinel — delivery contract

`no_agent` delivery:

- exit 0 + empty stdout → silent success
- exit 0 + stdout → deliver digest (HITL window / issues)
- exit ≠ 0 → cron marks job ERROR (“script failed”) even if health checks ran

So sentinel keeps **exit 0** when the script itself succeeded. Product failures and missing verifiers are reported via stdout + audit status (`error` / `partial`), not via non-zero exit. Missing tools → **`UNAVAILABLE`** (ops gap), not product **`FAIL`**.

### Daily ops review (`f6ops2100`) — detail

1. **Gather (script, $0):** `ops_day_digest.py` → `DAILY_DIGEST_*.md` + `{"wakeAgent": true}`.
2. **Review (agent):** skill `ops-daily-review` vs this doc’s expectations.
3. **Routing recency guard:** before any schedule/model edit, inspect same-day AUDIT, OPS_CHANGELOG, DECISIONS, and newest jobs backup. Same-day user-directed changes outrank stale docs. If ambiguous, report — do not normalize backward.
4. **Apply safe edits only:** prompt tightening, pin cheaper models, skill clarity, backup `jobs.json` before JSON edits. Restore night `deliver=local` if drifted. No deleting jobs, no raising all jobs to paid tiers, no disabling approvals, no prod force-merge.
5. **Persist:** append `OPS_CHANGELOG.md` + `DAILY_REPORTS.md`.
6. **Telegram (never silent):** concise Good / Bad / Human queue / Improvements / Cost / Tomorrow watch.

---

## Day pipeline (weekday mental model)

```
06:00  Brain consolidate
06:15  Mirror sync (HERMES_HOME ↔ ~/.hermes)
07:00  Project sentinel
07:30  GCP ops scan (optional; Telegram on issues)
09:30  CI scan (+ autofix if needed)     …also 15:30
09:30  Product manager (daily; weekend defer HITL)
09:00  Roadmap executor                  …also 11:00, 13:00, 15:00
22:00  Night executor window             …every 30m through 04:30 (Codex only; local)
*/5    Roadmap UI watchdog (:8888)
*/10   Audit ingest
*/15   Human queue watch (quiet Sat/Sun)
*/30   PR monitor (merge 24/7; Telegram Mon–Fri notify_window)
18:00  Market research (SILENT if unchanged)
21:00  Daily ops review + Telegram report
21:00  UI live scan (optional; + autofix if needed)
```

---

## Known gaps / intentional omissions

| Item | Status |
|------|--------|
| Gemini Flash cheap tier | Optional — wire only when an API key exists |
| Codex as daily chat default | Intentionally **not** — quota; escalate only |
| Roadmap UI autostart | Prefer `roadmap_ui_watchdog` + optional OS logon task |
| Live proof of every agent path | Smoke lightly; daily review + optional `h11uilive23` |
| Market prompt paths | Prefer `$HERMES_HOME/scripts/`; keep mirrors in sync |
| GitHub service account | Documented; set `HERMES_GH_TOKEN` for non-interactive scripts |
| Branch protection review bypass for bot | If rules require human review, green PRs stay held until `yes` / `hermes-approved` |
| GCP ops SA | Optional advanced — install script + credentials separately; no project IDs in kit |
| CI vs UI live overlap | Both may wake autofix; ≤1 open `hermes-autofix` PR/repo keeps it bounded |

---

## How to re-audit

1. Open this file.
2. `hermes auth list` — expect your configured providers (typically `xai-oauth` + `openai-codex` + local).
3. `hermes cron list` — jobs match the tables; models match `ops-config.yaml` (incl. optional night/UI/GCP when enabled).
4. Skim latest `brain/DAILY_DIGEST_*.md` and `OPS_CHANGELOG.md`.
5. Confirm Telegram home channel matches allowlisted user id.
6. `python install/doctor.py` from the kit (or `$HERMES_HOME` after install).

When changing the stack: update **this doc**, `OPS_MODELS.md`, and `brain/DECISIONS.md` in the same change.
