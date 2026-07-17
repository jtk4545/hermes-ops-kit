---
name: brain
description: Use when answering product, market, pipeline, buyer/acquirer, roadmap strategy, or ops-state questions. Read/write the shared Hermes brain/ bus used by cron and chat.
version: 1.0.0
author: Hermes Ops
license: MIT
metadata:
  hermes:
    tags: [brain, memory, ops, products, market]
    related_skills: [roadmap]
---

# Shared brain bus

Durable ops knowledge lives in files (not the tiny built-in MEMORY.md):

`$HERMES_HOME/brain/`

| File | Contents |
|------|----------|
| INDEX.md | Map + last consolidate |
| PRODUCTS.md | Per-product state/constraints |
| MARKET.md | Market snapshots |
| BUYERS.md | Buyers/acquirers |
| PIPELINES.md | CI/PR + local health |
| DECISIONS.md | HITL / durable decisions |
| PRINCIPLES.md | Role quality bars (executor/PM/market/autofix) |
| PR_QUALITY.md | Per-repo PR/CI lessons (living) |

## Required process

1. Before answering product/market/pipeline/strategy/quality questions, run:
   `python {{HERMES_PROJECTS_ROOT}}\AppData\Local\hermes\scripts\brain_read.py --sections INDEX,PRODUCTS,MARKET,BUYERS,PIPELINES,DECISIONS,PRINCIPLES,PR_QUALITY`
   Narrow with `--sections` / `--product <name>` when appropriate.
2. Cite what you read (which file/section).
3. Persist durable learnings with:
   `python {{HERMES_PROJECTS_ROOT}}\AppData\Local\hermes\scripts\brain_write.py PRODUCTS --append --text "..."`
   or `--replace-section "Heading"` / stdin. When using `--replace-section`, pass only the section body in `--text`; the script preserves/adds the heading.
4. Never dump task diaries or PR numbers into MEMORY.md — write brain files instead.
5. Cron jobs also use this bus (`skip_memory=True`); keep formats stable for them.
6. After editing PRINCIPLES or PR_QUALITY, run `python ...\scripts\sync_quality_skill.py` (brain consolidate also does this).

## Completion criteria

- Relevant brain sections were read before the answer
- Any new durable fact was written back to the correct brain file
