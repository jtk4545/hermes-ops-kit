# Cheap ops model over SSH (Qwen / Ollama)

PM, market, and daily-review jobs can run on a remote GPU box instead of a local 27B. Ollama usually binds **localhost only** on that box, so you do not hit the public IP on `:11434`. Open an SSH tunnel, then talk to a local port.

This is optional. If you skip it, point `models.pm` / `models.market` / `models.ops_review` at Grok (or another provider you already auth'd).

## What you need

| Item | Typical value | Override |
|------|----------------|----------|
| SSH host | your GPU box | `HERMES_OLLAMA_SSH_HOST` |
| SSH port | `22` | `HERMES_OLLAMA_SSH_PORT` |
| SSH user | your login | `HERMES_OLLAMA_SSH_USER` |
| Remote Ollama | `127.0.0.1:11434` | `HERMES_OLLAMA_REMOTE` |
| Local tunnel | `127.0.0.1:11435` | `HERMES_OLLAMA_LOCAL_PORT` |
| Model id | `qwen3.6-ops` | `ops-config.yaml` → `models.*` |

Prefer an SSH key in `authorized_keys`. Ask whoever owns the box for access; this kit does not ship credentials.

## 1. Open a tunnel

Leave this running while jobs need the model.

```bash
ssh -N \
  -o ServerAliveInterval=30 \
  -o ExitOnForwardFailure=yes \
  -L 11435:127.0.0.1:11434 \
  -p "$HERMES_OLLAMA_SSH_PORT" \
  "$HERMES_OLLAMA_SSH_USER@$HERMES_OLLAMA_SSH_HOST"
```

Windows helper (same env vars): `scripts/start-ollama-gpu-tunnel.ps1`.

After it starts:

| API | Base URL |
|-----|----------|
| Ollama native | `http://127.0.0.1:11435` |
| OpenAI-compatible | `http://127.0.0.1:11435/v1` |

Health checks:

```bash
curl -s http://127.0.0.1:11435/api/version
curl -s http://127.0.0.1:11435/api/tags
```

## 2. Wire Hermes

1. Add a provider in Hermes whose `api` is `http://127.0.0.1:11435/v1`.
2. Set `models.pm`, `models.market`, and `models.ops_review` in `ops-config.yaml` to that provider + model id.
3. Put Grok in the job fallback so a down tunnel does not stall the day.

Thinking models (Qwen 3.6, etc.) may put tokens in a reasoning field and leave `content` empty. Disable thinking for ops jobs (`think: false` / `reasoning_effort: none`).

## 3. Fallback

If the tunnel or remote Ollama is down, PM / market / ops-review should fail over to `xai-oauth` / `grok-4.6`. Coding jobs never use the cheap box as a coding fallback.
