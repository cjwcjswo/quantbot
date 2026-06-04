#Requires -Version 7
<#
.SYNOPSIS
  Stop the QuantBot dev stack started by start-dev.ps1.

.DESCRIPTION
  Terminates the recorded service process trees (bot, backend, frontend) INCLUDING
  the PowerShell windows they run in and all their child processes (uv/python/
  uvicorn/node). Uses .dev-run\pids.json; falls back to matching the
  "QuantBot - ..." window command lines if the pidfile is missing. Your own
  PowerShell session is never targeted.

.PARAMETER KeepDocker
  Do not stop the docker compose services (Postgres/Redis stay running).

.EXAMPLE
  .\scripts\stop-dev.ps1
  .\scripts\stop-dev.ps1 -KeepDocker
#>
[CmdletBinding()]
param(
  [switch]$KeepDocker
)

$Root    = Split-Path -Parent $PSScriptRoot
$Compose = Join-Path $Root "docker-compose.yml"
$RunDir  = Join-Path $Root ".dev-run"
$PidFile = Join-Path $RunDir "pids.json"

function Stop-Tree {
  param([int]$ProcessId, [string]$Label)
  if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
    return
  }
  Write-Host ("[stop] {0} (PID {1}) + children" -f $Label, $ProcessId) -ForegroundColor Yellow
  # /T kills the whole tree (pwsh window -> uv -> python/uvicorn/node), /F forces it.
  & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

$stopped = 0

# --- 1. recorded PIDs ----------------------------------------------------- #
if (Test-Path $PidFile) {
  $services = @(Get-Content $PidFile -Raw | ConvertFrom-Json)
  foreach ($s in $services) {
    Stop-Tree -ProcessId ([int]$s.pid) -Label $s.name
    $stopped++
  }
  Remove-Item $PidFile -Force
} else {
  Write-Warning "No $PidFile found; using window-title fallback."
}

# --- 2. fallback: any leftover QuantBot service windows ------------------- #
$leftover = Get-CimInstance Win32_Process -Filter "Name='pwsh.exe'" |
  Where-Object { $_.CommandLine -match "QuantBot - (Bot|API|Frontend)" }
foreach ($p in $leftover) {
  Stop-Tree -ProcessId ([int]$p.ProcessId) -Label "QuantBot window"
  $stopped++
}

if ($stopped -eq 0) {
  Write-Host "No QuantBot service processes were running." -ForegroundColor Cyan
}

# --- 3. infrastructure ---------------------------------------------------- #
if (-not $KeepDocker) {
  Write-Host "[infra] docker compose stop..." -ForegroundColor Cyan
  try {
    docker compose -f $Compose stop
  } catch {
    Write-Warning "docker compose stop failed: $_"
  }
}

Write-Host "Done." -ForegroundColor Green
