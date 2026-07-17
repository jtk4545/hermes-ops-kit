# DECISIONS

Durable product decisions from HITL and ops setup.

## Ops stack
- Shared brain bus is authoritative for cron + chat.
- Full design SoT: `~/.hermes/OPS_DESIGN.md`.
- Autonomy C: autofix and executor may open PRs; escalate on failures/ambiguity/HITL.
- Telegram is sparse: failures, HITL (weekdays), daily ops report only.
