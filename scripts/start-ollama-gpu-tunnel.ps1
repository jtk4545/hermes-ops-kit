# Persistent SSH tunnel: local port -> remote Ollama
# Host / user / ports come from env (no secrets in the kit).
#
#   HERMES_OLLAMA_SSH_HOST     required
#   HERMES_OLLAMA_SSH_USER     default: current user
#   HERMES_OLLAMA_SSH_PORT     default: 22
#   HERMES_OLLAMA_LOCAL_PORT   default: 11435
#   HERMES_OLLAMA_REMOTE       default: 127.0.0.1:11434

$ErrorActionPreference = "Stop"
$sshPath = "$env:WINDIR\System32\OpenSSH\ssh.exe"
if (Test-Path $sshPath) {
  $ssh = [pscustomobject]@{ Source = $sshPath }
} else {
  $ssh = Get-Command ssh -ErrorAction Stop
}
$hostName = $env:HERMES_OLLAMA_SSH_HOST
if (-not $hostName) {
  Write-Error "Set HERMES_OLLAMA_SSH_HOST (and usually HERMES_OLLAMA_SSH_USER / HERMES_OLLAMA_SSH_PORT)."
  exit 2
}
$port = if ($env:HERMES_OLLAMA_SSH_PORT) { $env:HERMES_OLLAMA_SSH_PORT } else { "22" }
$user = if ($env:HERMES_OLLAMA_SSH_USER) { $env:HERMES_OLLAMA_SSH_USER } else { $env:USERNAME }
$localPort = if ($env:HERMES_OLLAMA_LOCAL_PORT) { [int]$env:HERMES_OLLAMA_LOCAL_PORT } else { 11435 }
$remote = if ($env:HERMES_OLLAMA_REMOTE) { $env:HERMES_OLLAMA_REMOTE } else { "127.0.0.1:11434" }
$logDir = Join-Path $env:LOCALAPPDATA "hermes\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "ollama-gpu-tunnel.log"

function Write-Log($msg) {
  $line = "$(Get-Date -Format o) $msg"
  Add-Content -Path $log -Value $line
}

$existing = Get-NetTCPConnection -LocalPort $localPort -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  try {
    $version = Invoke-RestMethod -Uri "http://127.0.0.1:${localPort}/api/version" -TimeoutSec 5
    Write-Log "Tunnel healthy on localhost:$localPort (pid $($existing[0].OwningProcess), Ollama $($version.version))"
    exit 0
  } catch {
    Write-Log "Listener on $localPort is unhealthy; stopping pid $($existing[0].OwningProcess) and reconnecting"
    Stop-Process -Id $existing[0].OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }
}

Write-Log "Starting tunnel ${localPort} -> ${user}@${hostName}:${port} ${remote}"
$args = @(
  "-N",
  "-o", "BatchMode=yes",
  "-o", "ExitOnForwardFailure=yes",
  "-o", "ServerAliveInterval=30",
  "-o", "ServerAliveCountMax=3",
  "-o", "StrictHostKeyChecking=accept-new",
  "-L", "${localPort}:${remote}",
  "-p", "$port",
  "${user}@${hostName}"
)

Start-Process -FilePath $ssh.Source -ArgumentList $args -WindowStyle Hidden
Start-Sleep -Seconds 2
$ok = Get-NetTCPConnection -LocalPort $localPort -State Listen -ErrorAction SilentlyContinue
if ($ok) {
  Write-Log "Tunnel up on localhost:$localPort"
  exit 0
}
Write-Log "Tunnel failed to bind localhost:$localPort"
exit 1
