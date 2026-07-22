# Helper: print / optionally run IAM bindings for Hermes read-only GCP SA.
# Does NOT create keys unless -CreateKey is passed.
# All project IDs must be passed as parameters — no kit defaults.
param(
  [Parameter(Mandatory = $true)]
  [string]$HostProject,
  [string]$SaId = "hermes-gcloud-ops",
  [Parameter(Mandatory = $true)]
  [string[]]$Projects,
  [string]$BillingAccount = "",
  [string]$KeyOut = "",
  [switch]$CreateSa,
  [switch]$BindRoles,
  [switch]$CreateKey,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$SaEmail = "$SaId@$HostProject.iam.gserviceaccount.com"
$Roles = @(
  "roles/monitoring.viewer",
  "roles/logging.viewer",
  "roles/run.viewer",
  "roles/cloudfunctions.viewer",
  "roles/serviceusage.serviceUsageViewer"
)

if (-not $KeyOut) {
  $home = $env:HERMES_HOME
  if (-not $home) {
    if ($env:LOCALAPPDATA) {
      $home = Join-Path $env:LOCALAPPDATA "hermes"
    } else {
      $home = Join-Path $env:HOME ".local/share/hermes"
    }
  }
  $KeyOut = Join-Path $home "secrets\gcloud-ops.json"
}

$OutDir = Split-Path -Parent $KeyOut

function Invoke-Gcloud([string[]]$GcloudArgs) {
  Write-Host "gcloud $($GcloudArgs -join ' ')" -ForegroundColor DarkGray
  if ($WhatIf) { return }
  & gcloud @GcloudArgs
  if ($LASTEXITCODE -ne 0) { throw "gcloud failed: $($GcloudArgs -join ' ')" }
}

Write-Host "SA: $SaEmail" -ForegroundColor Cyan
Write-Host "Host project: $HostProject"
Write-Host "Projects: $($Projects -join ', ')"
Write-Host "Key out: $KeyOut"

if ($CreateSa) {
  Invoke-Gcloud @("config", "set", "project", $HostProject)
  Invoke-Gcloud @(
    "iam", "service-accounts", "create", $SaId,
    "--display-name=Hermes GCP ops (read-only)",
    "--project=$HostProject"
  )
}

if ($BindRoles) {
  foreach ($P in $Projects) {
    foreach ($R in $Roles) {
      Invoke-Gcloud @(
        "projects", "add-iam-policy-binding", $P,
        "--member=serviceAccount:$SaEmail",
        "--role=$R",
        "--condition=None"
      )
    }
  }
}

if ($BillingAccount) {
  Invoke-Gcloud @(
    "billing", "accounts", "add-iam-policy-binding", $BillingAccount,
    "--member=serviceAccount:$SaEmail",
    "--role=roles/billing.viewer"
  )
}

if ($CreateKey) {
  New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
  if (Test-Path $KeyOut) {
    Write-Host "Key already exists: $KeyOut (delete manually to rotate)" -ForegroundColor Yellow
  } else {
    Invoke-Gcloud @(
      "iam", "service-accounts", "keys", "create", $KeyOut,
      "--iam-account=$SaEmail",
      "--project=$HostProject"
    )
    if (-not $WhatIf) {
      setx HERMES_GCLOUD_SA_KEY $KeyOut | Out-Null
      Write-Host "Wrote $KeyOut and setx HERMES_GCLOUD_SA_KEY" -ForegroundColor Green
    }
  }
}

Write-Host @"

Next:
  1) gcloud auth login   # if needed
  2) .\install\setup-gcloud-ops-sa.ps1 -HostProject YOUR_HOST_PROJECT_ID -Projects @("YOUR_HOST_PROJECT_ID") -CreateSa -BindRoles [-BillingAccount 01XXX-...] [-CreateKey]
  3) Enable gcloud.enabled in ops-config and list projects (or copy templates/gcloud_projects.example.json)
  4) Restart Hermes / terminals
  5) python `$env:HERMES_HOME\scripts\gcloud-ops-scan.py
  Full walkthrough: docs/GCLOUD_OPS_SETUP.md
"@
