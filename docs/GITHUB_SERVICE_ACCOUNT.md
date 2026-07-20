# GitHub service account for Hermes ops

Prefer a dedicated bot so PRs/merges are attributable and your personal account is not the merge actor.

Scripts honor **`HERMES_GH_TOKEN`** first (then `GH_TOKEN`, then `gh auth login`).

## Recommended: machine user + fine-grained PAT

1. Create a GitHub user for the bot (e.g. `your-org-hermes-bot`).
2. Invite the bot to your org with write access on the repos listed in `ops-config.yaml`.
3. Create a **fine-grained PAT** owned by that user:
   - Permissions: **Contents** Read/Write, **Pull requests** Read/Write, **Metadata** Read, **Actions** Read
   - **Workflows** Read/Write only if PRs must edit workflows
4. Set a user environment variable (never commit the token):

   ```bash
   # macOS / Linux (shell profile)
   export HERMES_GH_TOKEN="github_pat_..."

   # Windows PowerShell
   setx HERMES_GH_TOKEN "github_pat_..."
   ```

   Restart the Hermes gateway so cron picks it up.

5. Verify:

   ```bash
   python "$HERMES_HOME/scripts/gh_ops.py"
   ```

   Expect the bot login, not your personal user.

6. Repo settings (each target repo or org ruleset):
   - Enable **Allow auto-merge**
   - Prefer **squash** merge
   - Give the bot a **bypass** for “required review” *or* require 0 reviews for `hermes-exec` / `hermes-autofix` — otherwise green PRs stay `REVIEW_REQUIRED` and Hermes will Telegram APPROVAL instead of merging
   - Do **not** let the bot bypass required status checks

## Merge policy

| Condition | Behavior |
|-----------|----------|
| Label `hermes-exec` or `hermes-autofix`, checks **green**, no approval hold | `gh pr merge --auto --squash --delete-branch` |
| Label `hermes-needs-approval`, or body marker `HERMES_NEEDS_APPROVAL` | **Do not merge** — APPROVAL ping |
| Checks red | RED alert (no merge) |
| Checks pending | Silent |
