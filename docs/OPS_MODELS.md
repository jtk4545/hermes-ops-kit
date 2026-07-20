# Hermes ops model routing

Configure providers in Hermes auth / `hermes model`, then set the same IDs under `models:` in `ops-config.yaml`.

| Job class | Suggested tier | Notes |
|-----------|----------------|-------|
| Sentinel, PR monitor, consolidate, day digest gather | `no_agent` / script | $0 — sentinel uses exit 0 on success (issues via stdout + audit); missing tools → `UNAVAILABLE` |
| Pipeline scan gate | script + wakeAgent | wakes autofix only on failures |
| PM + market + daily ops review | local or cheap cloud | default template: `bonsai-local` / `bonsai-27b` |
| CI autofix (first attempt) | mid-tier coding model | default template: `copilot` / `gpt-5.4` |
| Roadmap executor | strongest coding model you have | default template: `openai-codex` / `gpt-5.6-sol` |

**Cost ladder for new jobs:** `no_agent` → local/cheap → mid → strongest.

Configure Hermes `fallback_providers` so rate limits on the executor path failover instead of silent stalls.

Full design: `OPS_DESIGN.md`.

Telegram home channel must match your allowlisted user id. Cron deliver target for human-facing jobs: `telegram` (with `[SILENT]` / empty stdout for routine success).
