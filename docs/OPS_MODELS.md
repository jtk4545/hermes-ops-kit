# Hermes ops model routing

Configure providers in Hermes auth / `hermes model`, then set the same IDs under `models:` in `ops-config.yaml`.

Cheap ops = a remote or local small model (template: `qwen-gpu` / `qwen3.6-ops`) with Grok as backup. Coding jobs use Grok → Codex Sol. Local Bonsai is **off** in the current design (VRAM); do not auto-start it.

| Job class | Provider / model (template) | Schedule (timezone from config) | Notes |
|-----------|-----------------------------|----------------------------------|-------|
| Scripts (PR monitor, human queue, audit, …) | `no_agent` | frequent | **$0 — never throttle** |
| PM + market + daily ops review | `qwen-gpu` / `qwen3.6-ops` → `xai-oauth` / `grok-4.6` | 09:30 / 18:00 / 21:00 | SSH-tunneled Ollama or any cheap OpenAI-compatible host |
| CI autofix | `xai-oauth` / `grok-4.6` → `openai-codex` / `gpt-5.6-sol` | **09:30, 15:30** | Grok primary; Sol fallback; wake on branch CI **or** red Hermes PRs |
| Roadmap executor **day** (`d4exec1014`) | `xai-oauth` / `grok-4.6` → Codex Sol | **hourly 09:00–17:00 weekdays** | timebox **20–30m**; fallback finishes current slice only |
| Roadmap executor **night** (`d4execnight`) | `xai-oauth` / `grok-4.6` → Codex Sol | every 30m, **00:00–04:00** | **`deliver=local`, never Telegram**; stop on dual quota |
| UI live autofix (optional) | `xai-oauth` / `grok-4.6` → Codex Sol | 21:00 | frugal; wake on failures |
| GCP ops (optional) | `no_agent` | 07:30 | read-only scan; Telegram on issues |
| Interactive chat | `xai-oauth` / `grok-4.6` | — | typical desktop default |

**Cheap-model tunnel:** SSH local-forward `127.0.0.1:11435` → remote Ollama `:11434`. See [REMOTE_QWEN_GPU.md](REMOTE_QWEN_GPU.md). Example Windows helper: `scripts/start-ollama-gpu-tunnel.ps1` (host/user/port from env, not hardcoded).

**Fallback chains:** ops tier qwen → **Grok 4.6**; coding Grok → Codex Sol. No Bonsai auto-fallback.

**HARD STOP:** If Grok **and** Codex are exhausted/unavailable → coding crons stop, audit `QUOTA:`, do not thrash. Scripts + cheap-ops jobs still run.

**Notify window:** Mon–Fri **09:00–17:00** by default (`ops-config.yaml` → `notify_window`); daily ops report always allowed.

**Auth:** `hermes auth add xai-oauth` and `hermes auth add openai-codex` before creating agent jobs. A cheap-ops host needs an SSH key or whatever your tunnel uses.

**Cost ladder for new jobs:** `no_agent` → qwen-gpu (if tunnel) → day Grok → Codex Sol.

Full design: `OPS_DESIGN.md`.

Telegram home channel must match your allowlisted user id. Human-facing jobs: `telegram` (with `[SILENT]` / empty stdout for routine success). Night executor: `local` only.
