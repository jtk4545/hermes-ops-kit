# Model routing

Agent jobs do **not** require a specific vendor. Scripts (`no_agent`) never call a model.

## How selection works

1. Omit `models` (or `models: {}`) → every agent job uses Hermes' current default.
2. Set `models.default` → all agent parts inherit it.
3. Set a per-part key to override only that job class.
4. Optional `fallback: {provider, model}` on `default` or on a part. Fallback is for the in-flight slice only; jobs stop on 429/quota rather than inventing another provider.

```yaml
models:
  default:
    provider: your-provider    # from `hermes auth list`
    model: your-model
    fallback:                  # optional
      provider: other-provider
      model: other-model
  pm:
    provider: cheap-provider
    model: cheap-model
  # market, ops_review, autofix, executor, executor_night, ui_live
  # inherit default unless set
```

| Part | Jobs | Typical use |
|------|------|-------------|
| *(Hermes default)* | all agent jobs when `models` is empty | Fastest way to try the kit |
| `default` | every agent job unless overridden | One model for the whole shift |
| `pm` | Product manager 09:30 | Cheap / local is fine |
| `market` | Market research 18:00 | Same |
| `ops_review` | Daily ops report 21:00 | Same |
| `autofix` | CI scan + autofix 09:30 / 15:30 | Stronger coding model |
| `executor` | Day roadmap executor 09:00–17:00 weekdays | Same |
| `executor_night` | Night executor 00:00–04:00, `deliver=local` | Same or cheaper |
| `ui_live` | Optional UI live 21:00 | Same as autofix |

`install.py` writes the resolved provider/model onto each rendered cron job. Empty parts are left unpinned so Hermes keeps its default.

## Auth

Only auth the providers you actually list. There is no required Grok / Codex / Qwen / Bonsai stack.

Optional cheap remote host: [REMOTE_QWEN_GPU.md](REMOTE_QWEN_GPU.md).

## Hard stop

If the configured primary (and fallback, if any) is exhausted or down: coding jobs stop, audit `QUOTA:`, no extra providers. Script jobs keep running.

Notify window: Mon–Fri **09:00–17:00** by default (`ops-config.yaml` → `notify_window`); daily ops report always allowed.

Full design: `OPS_DESIGN.md`. Night executor: `local` only.
