# Hermes ops model routing

Configure providers in Hermes auth / `hermes model`, then set the same IDs under `models:` in `ops-config.yaml`.

| Job class | Suggested tier | Notes |
|-----------|----------------|-------|
| Sentinel, PR monitor, consolidate, day digest gather | `no_agent` / script | $0 — sentinel uses exit 0 on success (issues via stdout + audit); missing tools → `UNAVAILABLE` |
| Pipeline scan gate | script + wakeAgent | wakes autofix only on failures |
| PM + market + daily ops review | local or cheap cloud | default template: `bonsai-local` / `bonsai-27b` |
| CI autofix | coding model (frugal) | default template: `xai-oauth` / `grok-4.5` |
| Roadmap executor | coding model (frugal, timeboxed) | default template: `xai-oauth` / `grok-4.5` |

**Auth:** run `hermes auth add xai-oauth` (and your local/cheap provider) before creating agent jobs.

**Cost ladder for new jobs:** `no_agent` → local/cheap → Grok 4.5 → optional Codex failover.

Configure Hermes `fallback_providers` so Grok rate limits failover (e.g. to Codex) instead of silent stalls. Prefer a hard stop + `QUOTA:` audit when both coding providers are exhausted — do not thrash on Copilot/Bonsai for executor/autofix.

Full design: `OPS_DESIGN.md`.

Telegram home channel must match your allowlisted user id. Cron deliver target for human-facing jobs: `telegram` (with `[SILENT]` / empty stdout for routine success).
