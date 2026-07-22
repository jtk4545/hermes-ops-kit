---
name: auto-pr-fixer
description: Automatically detect failed CI pipeline runs on main/trunk and create fix PRs, then monitor PR checks to verify they pass
category: github
---

## When to use
- CI pipeline failures on main/trunk/dev/qa need investigation and remediation
- You want to detect, classify, and auto-create **real fix** PRs (not suggestion-only)
- Shared ops brain + PR monitor handle status after you open `hermes-autofix` PRs

## Brain contract (required)
1. `python $HERMES_HOME/scripts/brain_read.py --sections PRODUCTS,DECISIONS,PIPELINES,PRINCIPLES,PR_QUALITY`
2. Follow skill `quality-principles` (CI autofix section + that repo’s PR_QUALITY)
3. Apply real patches; open PR with label `hermes-autofix`
4. `brain_write.py PIPELINES --append` (+ PRODUCTS note if needed)
5. On durable lesson: `brain_write.py PR_QUALITY --append` then `sync_quality_skill.py`
6. Max 1 open autofix PR per repo; never force-push main

## What it does
1. Prefer script `pipeline-scan.py` output / `gh run list --repo X --json ...`
2. Filters to tracked branches (`main`, `trunk`, `dev`, `qa`, `routine/qa-loop`) and non-prod workflows
3. Classifies failures from job logs
4. Implements a real fix, commits, pushes, opens labeled PR
5. Relies on `pr-monitor.py` cron for check polling / **auto-merge on green** (unless `hermes-needs-approval`). Prefer enabling `gh pr merge --auto --squash --delete-branch` when opening the PR.

## Pipeline filtering (IMPORTANT)

**Always skip these workflow names:**
- `release`, `prod`, `production`, `hotfix`
- `status page` / `status-page` (high-frequency noise)
- `dependabot` / `dependency graph`

**Only include these workflow patterns (lowercase substring match):**
- `pr validation`, `ci`, `qa`, `qa integration`
- `gcp dev`, `dev deploy`, `deploy`, `deploy to dev`
- `nightly`, `e2e`, `test`, `lint`

If a workflow name doesn't match an include pattern, **skip it**.

**Scanner note:** `pipeline-scan.py` also polls `critical_workflows` from `ops-config.yaml` so noisy schedules cannot hide real failures from `gh run list --limit N`.

## Failure classification taxonomy

| Classification | Trigger pattern in logs | Fix suggestion example |
|---|---|---|
| `lint-ruff` | `ruff` | `ruff check . --fix` |
| `lint-go` | `golangci-lint` or `go-lint` | `golangci-lint --fix` |
| `typecheck` | `tsc` + `TypeError` | `npx tsc --noEmit` |
| `test` | `pytest`/`npm test` + `fail` | `npm test -- --verbose` |
| `test-go` | `go test` or `go_test` | `go test -v` |
| `build` | `go build`/`go vet` | `go build ./...` |
| `lint-eslint` | `eslint` or `tsc --noEmit` | `npx eslint . --fix` |
| `build-gradle` | `gradlew`/`gradle` | `gradlew verify --parallel` |
| `docker` | `docker build`/`docker-compose` | `docker build` locally |
| `deploy` | `deploy` + `gcp`/`cloud` | Verify secrets/env vars |
| `general` | none of the above | Review full job logs |

## PR check monitoring
After creating a PR, poll `gh pr check-status` every 15 seconds (10 min timeout) and report:
- `OK` — all checks passed
- `FAIL` — one or more checks failed (note which)
- `ERROR` — check errors (not failures)

## File
Script: `~/.hermes/scripts/ai-pr-fixer.py`

Usage:
- `python ai-pr-fixer.py` — report-only mode
- `python ai-pr-fixer.py --auto` — create PRs and monitor checks

## Pitfalls
- Create PRs through `python "$HERMES_HOME/scripts/gh_ops.py" create-pr ... --label hermes-autofix`, not bare `gh pr create`. This adds the model attribution label/footer and preserves the role label.
- Local repos may have SSH remotes (`git@github.com:...`). The script needs to parse both HTTPS and SSH URLs to detect the owner/repo.
- The `gh` CLI needs `--repo` flag for `gh run list`. Without it, `gh` uses the current repo context which may not be set.
- If a PR fails to create (auth issue, repo not found), the script should report the failure and continue.
- The `gh` CLI needs `--repo` flag for `gh run list`. Without it, `gh` uses the current repo context which may not be set.
- `gh run` has **no `jobs` subcommand** — jobs must be fetched via the REST API: `gh api /repos/{repo}/runs/{run_number}/jobs`. Same for logs: `gh api /repos/{repo}/runs/{run_number}/jobs/{job_name}/logs`.
- The GitHub API uses `headBranch` (not `ref`) and `number` (not `id`) — always verify field names against actual JSON output before building filters on them.
- **`gh run list` has no `--json` flag** — parse the native TSV output. Column indices: `[0]status`, `[1]conclusion`, `[2]name`, `[3]workflowName`, `[4]headBranch`, `[8]startedAt`.
- **Job log fetch often times out** (API rate limits on this host). Always guard with try/except and fall back to "general" classification when logs are unavailable.
- **Branch tracking must be explicit** — configure `tracked_branches` in `ops-config.yaml`. Don't assume every repo uses every branch.
- Always add newly-discovered workflows (like `deploy to dev`) from `SKIP_WORKFLOW_PATTERNS` to `INCLUDE_WORKFLOW_PATTERNS` to ensure they get analyzed, not silently ignored.
