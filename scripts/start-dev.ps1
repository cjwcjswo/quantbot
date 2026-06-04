#Requires -Version 7
<#
.SYNOPSIS
  Start the QuantBot dev stack (docker infra + bot + backend API + frontend) on Windows.

.DESCRIPTION
  Launches each service in its own PowerShell window so you can watch its logs, and
  records the spawned PIDs to .dev-run\pids.json so stop-dev.ps1 can terminate the
  exact process trees (including those PowerShell windows).

.PARAMETER SkipDocker
  Do not run "docker compose up -d" (use if Postgres/Redis already run elsewhere).

.PARAMETER SkipFrontend
  Do not start the React dev server.

.EXAMPLE
  .\scripts\start-dev.ps1
  .\scripts\start-dev.ps1 -SkipDocker
#>
[CmdletBinding()]
param(
  [switch]$SkipDocker,
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root     = Split-Path -Parent $PSScriptRoot          # repo root (scripts/ lives under it)
$FrontDir = Join-Path $Root "apps\frontend"
$Compose  = Join-Path $Root "docker-compose.yml"
$RunDir   = Join-Path $Root ".dev-run"
$PidFile  = Join-Path $RunDir "pids.json"

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

# --- guard against double-start ------------------------------------------- #
if (Test-Path $PidFile) {
  $existing = @(Get-Content $PidFile -Raw | ConvertFrom-Json)
  $alive = $existing | Where-Object { Get-Process -Id $_.pid -ErrorAction SilentlyContinue }
  if ($alive) {
    Write-Warning "Some services already appear to be running (see $PidFile)."
    Write-Warning "Run .\scripts\stop-dev.ps1 first, then start again."
    return
  }
}

# --- 1. infrastructure (Postgres + Redis) --------------------------------- #
if (-not $SkipDocker) {
  Write-Host "[infra] docker compose up -d (postgres + redis)..." -ForegroundColor Cyan
  try {
    docker compose -f $Compose up -d
  } catch {
    Write-Warning "docker compose failed: $_"
    Write-Warning "Bot needs Redis and (optionally) Postgres. Continuing anyway."
  }
}

# --- 2. frontend deps (first run only) ------------------------------------ #
if (-not $SkipFrontend -and -not (Test-Path (Join-Path $FrontDir "node_modules"))) {
  Write-Host "[frontend] installing npm dependencies (first run)..." -ForegroundColor Cyan
  Push-Location $FrontDir
  try { npm install } finally { Pop-Location }
}

# --- helper: spawn a service in its own titled PowerShell window ----------- #
function Start-DevService {
  param([string]$Title, [string]$WorkDir, [string]$Command)
  $inner = "`$host.UI.RawUI.WindowTitle='$Title'; Set-Location '$WorkDir'; Write-Host '== $Title ==' -ForegroundColor Green; $Command"
  $proc  = Start-Process pwsh -PassThru -ArgumentList @("-NoExit", "-NoProfile", "-Command", $inner)
  Write-Host ("[start] {0} -> PID {1}" -f $Title, $proc.Id) -ForegroundColor Green
  return [pscustomobject]@{ name = $Title; pid = $proc.Id }
}

$services = @()
$services += Start-DevService "QuantBot - Bot"     $Root     "uv run python -m apps.bot.main"
$services += Start-DevService "QuantBot - API"     $Root     "uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"
if (-not $SkipFrontend) {
  $services += Start-DevService "QuantBot - Frontend" $FrontDir "npm run dev"
}

@($services) | ConvertTo-Json -Depth 4 | Set-Content -Path $PidFile -Encoding UTF8

Write-Host ""
Write-Host "Started services (PIDs saved to $PidFile):" -ForegroundColor Cyan
$services | Format-Table -AutoSize
Write-Host "  API      : http://localhost:8000  (health: /health, docs: /docs)"
Write-Host "  Frontend : http://localhost:5173"
Write-Host ""
Write-Host "The bot boots to STANDBY. Start PAPER trading with:" -ForegroundColor Yellow
Write-Host '  Invoke-RestMethod -Method Post http://localhost:8000/bot/start -ContentType application/json -Body ''{"mode":"PAPER"}'''
Write-Host ""
Write-Host "Stop everything (and close those windows) with: .\scripts\stop-dev.ps1" -ForegroundColor Yellow
