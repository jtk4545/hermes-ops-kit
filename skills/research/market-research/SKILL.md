---
name: market-research
description: Daily market + buyer scans for configured products. Use for e5market184 cron and any product/pricing/competitor research that writes brain MARKET/BUYERS.
version: 1.0.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [market, research, buyers, pricing, competitors, brain]
    related_skills: [brain, quality-principles]
---

# Market research

## Skills vs tools (do not confuse)

- There is **no** skill named `web`. Web capability is the **`web` toolset**: tools `web_search` and `web_extract`.
- This job should load skills: `market-research`, `brain`, `quality-principles`.
- Cron `enabled_toolsets` should include `web`, `terminal`, `file` (not a skill named web).

## Required first steps

1. `python "$HERMES_HOME/scripts/ops_audit.py" recent --job e5market184 -n 5`
2. `python "$HERMES_HOME/scripts/brain_read.py" --sections PRODUCTS,BUYERS,MARKET,PRINCIPLES`
3. Prefer **live sources every run** — do not only rewrite yesterday’s hypotheses.

## How to gather evidence (in order)

1. **`web_search`** — pricing, competitors, demand per product listed in `ops-config.yaml` → `products` (and `PRODUCTS.md`). Backend should be **ddgs** (no API key) when available. If search errors, try again once; then fall back to step 2.
2. **`web_extract`** — only if a provider is available. If extract fails (no Firecrawl key), **do not stop**.
3. **Terminal fallback (required when extract unavailable):** `curl -fsSL` or `python -c` fetch of relevant vendor pricing pages for your products. Parse visible $ and plan names only; note “direct page check” in MARKET.
4. Never invent prices. If a page blocks bots, say so and keep prior verified figures with date.

## Persist

```text
python "$HERMES_HOME/scripts/brain_write.py" MARKET --replace-section "Latest scan" --stdin
python "$HERMES_HOME/scripts/brain_write.py" BUYERS --replace-section "Latest scan" --stdin
```

Structure: dated header, per-product bullets (competitors, pricing moves, demand), confidence/source coverage line, PM actions.

Example product key from kit config: `example-app` (replace with your `products:` list).

## Delivery / audit

- Material change → short Telegram (weekday notify_window); else final response exactly `[SILENT]` after audit.
- Always: `ops_audit.py append --job e5market184 --name "Market research" --status ok|partial|silent|error|blocked ...`
- Use `--status partial` if search worked but some products lacked sources; `--status error` only if you could not write brain at all.
- If **both** web_search and curl fail: audit `blocked` with `--human-gate "ACTION: Configure web search (ddgs installed or FIRECRAWL_API_KEY / BRAVE_SEARCH_API_KEY)"` — weekday Telegram only.

## Quality bar

Follow PRINCIPLES → Market research. Actionable notes for PM; cite source names lightly; honesty over volume.
