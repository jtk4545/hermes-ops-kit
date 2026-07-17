# Hermes Ops Kit — Architecture

This kit is an **ops layer on top of Hermes Agent**. It does not replace Hermes; it adds a shared brain, roadmap UI, audit control plane, and a multi-job daily pipeline.

## System overview

```mermaid
flowchart LR
  subgraph inputs [Inputs]
    Config[ops-config.yaml]
    GH[GitHub]
    Human[Human HITL]
  end

  subgraph runtime [Runtime]
    Gateway[Hermes gateway cron]
    Scripts[Scripts no_agent]
    Agents[Agent jobs + skills]
  end

  subgraph state [State]
    Brain[Brain md files]
    Roadmap[roadmaps.json]
    Audit[AUDIT.jsonl]
  end

  subgraph outputs [Outputs]
    PRs[PRs + auto-merge]
    UI[UI :8888]
    TG[Telegram sparse]
  end

  Config --> Scripts
  Config --> Agents
  Gateway --> Scripts
  Gateway --> Agents
  Scripts --> Brain
  Scripts --> Audit
  Agents --> Brain
  Agents --> Roadmap
  Agents --> Audit
  Agents --> PRs
  GH --> Scripts
  Scripts --> PRs
  Human --> Roadmap
  Roadmap --> UI
  Brain --> UI
  Audit --> UI
  Agents -->|HITL failure daily report| TG
  Scripts -->|RED APPROVAL reminders| TG
```

**Read this left → right:** config and GitHub feed script/agent jobs driven by the Hermes gateway. Jobs mutate brain/roadmap/audit. Humans clear HITL via the UI. Telegram stays quiet except failures, approvals, and the daily report.

## Day pipeline

```text
06:00  Brain consolidate
06:15  Sync HERMES_HOME ↔ ~/.hermes mirrors
07:00  Project sentinel (local health → PIPELINES)
08:00  CI scan (+ autofix agent if wakeAgent)   …also 12/16/20
09:30  Product manager (roadmap classify)
10:00  Roadmap executor                         …also 14:00
*/15   Human queue watch (Telegram backoff; quiet weekends)
*/30   PR monitor (merge-on-green; APPROVAL weekdays)
*/10   Audit ingest (backfill agent outputs)
*/5    Roadmap UI watchdog (:8888)
18:00  Market research → MARKET / BUYERS
21:00  Daily ops review + Telegram day report
```

```mermaid
flowchart TD
  c0600[06:00 consolidate] --> c0615[06:15 mirror sync]
  c0615 --> c0700[07:00 sentinel]
  c0700 --> c0800[08:00 CI scan]
  c0800 -->|wakeAgent| autofix[Autofix agent]
  c0800 --> c0930[09:30 PM]
  c0930 --> c1000[10:00 / 14:00 executor]
  c1000 --> prs[hermes-exec PRs]
  autofix --> afPRs[hermes-autofix PRs]
  prs --> monitor[*/30 PR monitor]
  afPRs --> monitor
  monitor -->|green| merge[Auto-merge]
  monitor -->|hold| approval[APPROVAL Telegram]
  c0930 -->|blocked| needsYou[Needs you UI]
  c1000 -->|blocked| needsYou
  needsYou --> hq[*/15 human queue]
  hq -->|backoff| tgRemind[Telegram reminder]
  needsYou -->|release| c1000
  c1800[18:00 market] --> brain[Brain MARKET BUYERS]
  c2100[21:00 ops review] --> dayReport[Telegram day report]
```

## Control planes

| Plane | SoT | Purpose |
|-------|-----|---------|
| Brain | `$HERMES_HOME/brain/*.md` | Product intent, market, decisions, quality bars |
| Roadmap | `~/.hermes/roadmaps.json` | Agent vs human work queue + HITL steps |
| Audit | `brain/AUDIT.jsonl` | What ran, what blocked, PR/repo links |
| Cron | `$HERMES_HOME/cron/jobs.json` | Schedules, models, prompts (live; not shipped) |
| Config | `ops-config.yaml` | Org, repos, timezone, models, local checks |

## Job kinds

- **Script / `no_agent`:** stdout delivered when non-empty (silent = empty). Examples: sentinel, PR monitor, UI watchdog, audit ingest.
- **Script + agent:** script prints context / `{"wakeAgent": true|false}`; agent runs only when needed (CI autofix) or always (daily digest).
- **Agent:** LLM with skills; final response must be exactly `[SILENT]` unless HITL, failure, or daily report.

## Sparse Telegram

Deliver only:

1. Failures / needs attention
2. Human ACTION / APPROVAL packets (weekdays)
3. Daily ops report (`f6ops2100`)

Everything else → audit + UI.

## Merge policy

| Labels | Checks | Behavior |
|--------|--------|----------|
| `hermes-exec` or `hermes-autofix` | green | Auto-merge squash |
| + `hermes-needs-approval` | green | Hold; APPROVAL Telegram (weekdays) |
| either | red | Telegram RED; no merge |

Prefer `HERMES_GH_TOKEN` bot identity (see `GITHUB_SERVICE_ACCOUNT.md`).

## Config → runtime

```mermaid
flowchart LR
  cfg[ops-config.yaml] --> opsConfig[ops_config.py]
  opsConfig --> scripts[pipeline-scan gh_ops sentinel roadmap UI]
  cfg --> render[render_jobs.py]
  render --> createGuide[CREATE_JOBS.md]
  createGuide --> hermesCron[hermes cron create]
```
