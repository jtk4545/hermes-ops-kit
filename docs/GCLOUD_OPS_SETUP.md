# Hermes GCP ops — read-only service account setup

Hermes can use a **service account JSON key** (not a personal OAuth token) for Cloud Run / Functions / logging / billing visibility.

| Item | Location |
|------|----------|
| Key path (default) | `$HERMES_HOME/secrets/gcloud-ops.json` |
| Env overrides | `HERMES_GCLOUD_SA_KEY` or `GOOGLE_APPLICATION_CREDENTIALS` |
| Projects config | `ops-config` → `gcloud.projects[]`, or `$HERMES_HOME/scripts/gcloud_projects.json` |
| Scan script | `gcloud-ops-scan.py` (optional cron `h12gcloud0730`) |
| SA helper | `install/setup-gcloud-ops-sa.ps1` |

**Never commit the key. Never grant deploy/admin/Secret Manager accessor.**

---

## 0. Prerequisites

1. Re-auth your user (needed once to *create* the SA):

```powershell
gcloud auth login
gcloud auth list
```

2. Confirm you can see projects:

```powershell
gcloud projects list --format="table(projectId,name)"
```

3. Enable the module in `ops-config.yaml`:

```yaml
gcloud:
  enabled: true
  projects:
    - id: YOUR_GCP_PROJECT_ID
      label: example-dev
      region: us-central1
      watch_run_services: []
      enabled: true
  thresholds:
    cloud_run_error_logs_1h: 25
    daily_cost_usd_warn: 50.0
```

Or copy `templates/gcloud_projects.example.json` → `$HERMES_HOME/scripts/gcloud_projects.json` and edit project ids.

---

## 1. Create the ops service account (once, in a host project)

Pick any project you own as the **host** (where the SA lives):

```powershell
$HOST = "YOUR_HOST_PROJECT_ID"
$SA_ID = "hermes-gcloud-ops"
$SA_EMAIL = "$SA_ID@$HOST.iam.gserviceaccount.com"

gcloud config set project $HOST

gcloud iam service-accounts create $SA_ID `
  --display-name="Hermes GCP ops (read-only)" `
  --project=$HOST
```

Or use the parameterized helper:

```powershell
.\install\setup-gcloud-ops-sa.ps1 `
  -HostProject YOUR_HOST_PROJECT_ID `
  -Projects @(
    "YOUR_HOST_PROJECT_ID",
    "YOUR_OTHER_PROJECT_ID"
  ) `
  -CreateSa -BindRoles
```

---

## 2. Grant read-only roles on **each** project

```powershell
$SA_EMAIL = "hermes-gcloud-ops@YOUR_HOST_PROJECT_ID.iam.gserviceaccount.com"
$PROJECTS = @(
  "YOUR_HOST_PROJECT_ID"
  # add more project ids here
)

$ROLES = @(
  "roles/monitoring.viewer",
  "roles/logging.viewer",
  "roles/run.viewer",
  "roles/cloudfunctions.viewer",
  "roles/serviceusage.serviceUsageViewer"
)

foreach ($P in $PROJECTS) {
  foreach ($R in $ROLES) {
    gcloud projects add-iam-policy-binding $P `
      --member="serviceAccount:$SA_EMAIL" `
      --role=$R `
      --condition=None
  }
}
```

Optional broader read (still no write): `roles/viewer` instead of the list above.

---

## 3. Billing (optional but recommended for cost watch)

```powershell
gcloud billing accounts list
```

```powershell
$BILLING = "01XXXX-XXXXXX-XXXXXX"   # from list
$SA_EMAIL = "hermes-gcloud-ops@YOUR_HOST_PROJECT_ID.iam.gserviceaccount.com"

gcloud billing accounts add-iam-policy-binding $BILLING `
  --member="serviceAccount:$SA_EMAIL" `
  --role="roles/billing.viewer"
```

Put the same id into `gcloud.billing_account_id` / `gcloud_projects.json`.

---

## 4. Create the JSON key and install it locally

```powershell
$HOST = "YOUR_HOST_PROJECT_ID"
$SA_EMAIL = "hermes-gcloud-ops@$HOST.iam.gserviceaccount.com"
$OUT_DIR = Join-Path $env:HERMES_HOME "secrets"
if (-not $OUT_DIR -or -not (Test-Path (Split-Path $OUT_DIR))) {
  $OUT_DIR = Join-Path $env:LOCALAPPDATA "hermes\secrets"
}
$OUT = Join-Path $OUT_DIR "gcloud-ops.json"

New-Item -ItemType Directory -Force -Path $OUT_DIR | Out-Null

gcloud iam service-accounts keys create $OUT `
  --iam-account=$SA_EMAIL `
  --project=$HOST

setx HERMES_GCLOUD_SA_KEY $OUT
```

Or: `.\install\setup-gcloud-ops-sa.ps1 -HostProject YOUR_HOST_PROJECT_ID -CreateKey`

Restart Hermes gateway / terminals so cron sees `HERMES_GCLOUD_SA_KEY`.

---

## 5. Verify

```powershell
$env:HERMES_GCLOUD_SA_KEY = "$env:HERMES_HOME\secrets\gcloud-ops.json"
gcloud auth activate-service-account --key-file=$env:HERMES_GCLOUD_SA_KEY
gcloud run services list --project=YOUR_GCP_PROJECT_ID --region=us-central1
python "$env:HERMES_HOME\scripts\gcloud-ops-scan.py"
```

Expect PIPELINES section **GCP ops scan** updated. Exit code `1` only when issues are found (Telegram via cron deliver).

---

## 6. What Hermes does with this

| Item | Behavior |
|------|----------|
| Cron `h12gcloud0730` | Optional daily ~07:30 (timezone from ops-config), `no_agent` |
| On issues | Writes PIPELINES + COSTS; Telegram via job deliver; **does not** wake code autofix |
| Daily ops review | Can summarize GCP ops from PIPELINES |

---

## Security notes

- Rotate keys yearly (or on laptop loss): delete old key in IAM → create new → replace file.
- Do **not** add `roles/secretmanager.secretAccessor`, `roles/editor`, or deploy roles.
- Prefer one SA + multi-project bindings over one key per project.
