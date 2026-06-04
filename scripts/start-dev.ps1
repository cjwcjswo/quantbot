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
# Let native CLIs (docker/uv/npm) report failure via $LASTEXITCODE instead of throwing,
# so we can handle Docker-not-ready gracefully.
$PSNativeCommandUseErrorActionPreference = $false
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

# --- docker helpers ------------------------------------------------------- #
function Test-DockerDaemon {
  docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
  return ($LASTEXITCODE -eq 0)
}

function Initialize-Docker {
  param([int]$TimeoutSec = 180)
  $cli = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $cli) {
    Write-Warning "Docker CLI not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    return $false
  }
  if (Test-DockerDaemon) { return $true }

  # daemon not up yet -> try to launch Docker Desktop, then wait for it.
  # docker.exe is at ...\Docker\Docker\resources\bin\docker.exe; the launcher is 3 levels up.
  $derived = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $cli.Source))
  $candidates = @(
    (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Docker\Docker\Docker Desktop.exe"),
    (Join-Path $derived "Docker Desktop.exe")
  ) | Where-Object { $_ -and (Test-Path $_) }
  $desktop = $candidates | Select-Object -First 1
  if ($desktop) {
    Write-Host "[infra] Docker daemon not running; launching Docker Desktop..." -ForegroundColor Cyan
    Start-Process -FilePath $desktop | Out-Null
  } else {
    Write-Warning "Docker daemon not running and 'Docker Desktop.exe' was not found."
    Write-Warning "Start Docker Desktop manually, then re-run."
  }

  Write-Host "[infra] waiting for Docker daemon (up to $TimeoutSec s)..." -ForegroundColor Cyan
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
    if (Test-DockerDaemon) {
      Write-Host "[infra] Docker daemon ready." -ForegroundColor Green
      return $true
    }
    Start-Sleep -Seconds 3
  }
  Write-Warning "Docker daemon did not become ready within $TimeoutSec s."
  return $false
}

function Wait-ComposeHealthy {
  param([int]$TimeoutSec = 60)
  Write-Host "[infra] waiting for postgres/redis to become healthy..." -ForegroundColor Cyan
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
    $pg = (docker inspect -f '{{.State.Health.Status}}' quantbot-postgres 2>$null)
    $rd = (docker inspect -f '{{.State.Health.Status}}' quantbot-redis 2>$null)
    if ($pg -eq 'healthy' -and $rd -eq 'healthy') {
      Write-Host "[infra] infra healthy." -ForegroundColor Green
      return
    }
    Start-Sleep -Seconds 2
  }
  Write-Warning "Infra not fully healthy yet; services will keep retrying to connect."
}

# --- 1. infrastructure (Postgres + Redis) --------------------------------- #
if (-not $SkipDocker) {
  if (Initialize-Docker) {
    Write-Host "[infra] docker compose up -d (postgres + redis)..." -ForegroundColor Cyan
    docker compose -f $Compose up -d
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "docker compose up failed (exit $LASTEXITCODE). The bot needs Redis to run."
    } else {
      Wait-ComposeHealthy
    }
  } else {
    Write-Warning "Skipping infra. The bot needs Redis (and ideally Postgres) to run."
    Write-Warning "Options: start Docker Desktop and re-run, OR provide your own Redis/Postgres"
    Write-Warning "         and re-run with -SkipDocker (set DATABASE_URL/REDIS_URL in .env)."
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
