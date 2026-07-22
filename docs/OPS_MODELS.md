# Hermes ops model routing

Configure providers in Hermes auth / `hermes model`, then set the same IDs under `models:` in `ops-config.yaml`.

| Job class | Provider / model (template default) | Schedule (timezone from config) | Notes |
|-----------|-------------------------------------|----------------------------------|-------|
| Scripts (PR monitor, human queue, audit, …) | `no_agent` | frequent | **$0 — never throttle** |
| PM + market + daily ops review | `bonsai-local` / `bonsai-27b` | 09:30 / 18:00 / 21:00 | free local |
| CI autofix | `openai-codex` / `gpt-5.6-sol` | **09:30, 15:30** | primary; one Grok try only if Codex exhausts mid-fix; silent if green |
| Roadmap executor **day** (`d4exec1014`) | `xai-oauth` / `grok-4.5` → Composer 2.5 → Codex Sol | **09:00, 11:00, 13:00, 15:00** | timebox **20–30m**; fallbacks finish current slice only |
| Roadmap executor **night** (`d4execnight`) | `openai-codex` / `gpt-5.6-sol` | every 30m, **22:00–04:30** | strict empty fallback; **`deliver=local`, never Telegram**; stop on 429/auth/quota |
| UI live autofix (optional) | `xai-oauth` / `grok-4.5` | 21:00 | frugal; wake on failures |
| GCP ops (optional) | `no_agent` | 07:30 | read-only scan; Telegram on issues |
| Interactive chat | prefer Grok carefully / manual | — | avoid burning weekly Grok on chat thrash |

**Alternate lean day schedule (document only):** some installs prefer day executor at 10:00 + 14:00 and CI at 08/12/16/20. The portable Grok-frugal template default is the four-slot day (`09,11,13,15`) + CI (`09:30,15:30`) above — change via cron registry / config comments, not by inventing a second template.

**Executor audit:** Both day and night prompts append directly on every outcome (including `[SILENT]`); the no-agent audit ingester also covers both and reconciles scheduler completion state when a run has no usable response artifact.

**Fallback chains:** day executor Grok 4.5 → **Composer 2.5 → Codex Sol** for the in-flight slice; UI-live Grok → Codex Sol; night executor has no fallback. No Copilot/Bonsai auto-fallback for coding.

**HARD STOP:** If Grok **and** Codex are exhausted/unavailable → coding crons stop, audit `QUOTA:`, do not thrash.

**Notify window:** Mon–Fri **09:00–17:00** by default (`ops-config.yaml` → `notify_window`); daily ops report always allowed.

**Auth:** run `hermes auth add xai-oauth` and `hermes auth add openai-codex` (plus local/cheap) before creating agent jobs.

**Cost ladder for new jobs:** `no_agent` → Bonsai → day Grok → Codex Sol for CI/night execution.

Full design: `OPS_DESIGN.md`.

Telegram home channel must match your allowlisted user id. Cron deliver target for human-facing jobs: `telegram` (with `[SILENT]` / empty stdout for routine success). Night executor: `local` only.
