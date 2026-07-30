# Wardress updater (Windows, Docker Desktop).
#
#   powershell -ExecutionPolicy Bypass -File scripts\update.ps1
#
# What it does, in order:
#   1. Verifies Docker Desktop is running and .env exists.
#   2. Pulls the latest source (git fast-forward, only if this is a git
#      checkout with a remote - skipped silently otherwise).
#   3. Pulls newer base images and rebuilds the Wardress images
#      serially in the foreground.
#   4. Runs any new database migrations.
#   5. Restarts the stack. The beat scheduler is always force-recreated:
#      compose does not recreate a running beat container when only its
#      (shared) image changed, so without this step beat keeps running
#      the OLD code. Same for the optional telegram-bot if it is running.
#
# Your data (Postgres volume, scan artifacts) and your .env are never
# touched. Safe to re-run. Exits non-zero with a readable message on
# any failure.

[CmdletBinding()]
param(
    # Skip the git pull (e.g. you manage source updates yourself).
    [switch]$NoGitPull
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot ".env"

# Shared helpers (Fail/Step/Invoke-*, dynamic image discovery, retries).
. (Join-Path $PSScriptRoot "lib.ps1")

# Set total steps for progress tracking
Set-TotalSteps 11

# --- 1. Preconditions ----------------------------------------------------

Step "Checking Docker Desktop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail ("Docker is not installed (the 'docker' command was not found). " +
        "Wardress requires Docker Desktop: https://www.docker.com/products/docker-desktop/")
}
if (-not (Invoke-Quiet { docker info })) {
    Fail ("Docker Desktop is installed but the engine is not running. " +
        "Start Docker Desktop, wait for it to say 'Engine running', then re-run this script.")
}

Set-Location $RepoRoot

if (-not (Test-Path $EnvFile)) {
    Fail ".env not found - run scripts\install.ps1 first."
}

Write-Progress-Done "Prerequisites verified"

# --- 2. Pull source ------------------------------------------------------

if (-not $NoGitPull) {
    $isGitRepo = (Test-Path (Join-Path $RepoRoot ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)
    if ($isGitRepo) {
        if (Invoke-Quiet { git remote get-url origin }) {
            Step "Pulling the latest source (git fast-forward only)"
            git pull --ff-only
            if ($LASTEXITCODE -ne 0) {
                Fail ("git pull failed (local changes or a diverged branch?). " +
                    "Resolve it manually, or re-run with -NoGitPull to update from the current checkout.")
            }
            Write-Progress-Done "Source updated"
        } else {
            Write-Host "    No git remote configured, skipping source update" -ForegroundColor Yellow
        }
    } else {
        Write-Host "    Not a git repository or git not installed, skipping source update" -ForegroundColor Yellow
    }
}

# --- Pre-flight: TypeScript check ----------------------------------------

Step "Pre-flight TypeScript validation"

# Install/update frontend dependencies before TypeScript check
$frontendPath = Join-Path $RepoRoot "frontend"
if (Test-Path (Join-Path $frontendPath "package.json")) {
    Push-Location $frontendPath
    try {
        Write-Progress-Inline "Updating frontend dependencies..."
        pnpm install --frozen-lockfile | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Fail "Failed to install frontend dependencies"
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-CompilationErrors $RepoRoot)) {
    Fail "TypeScript compilation errors detected. Fix them before rebuilding Docker images."
}

# --- 3. Pull base images + rebuild (serially, in the foreground) ---------

Step "Discovering base images"
# Discovered dynamically from the Dockerfiles + compose config (nothing
# hardcoded), so it always matches the real stack.
$baseImages = @()
$baseImages += Get-BuildBaseImages $RepoRoot
$baseImages += Get-ComposeRemoteImages
Write-Progress-Done "Found $($baseImages.Length) base images"

Step "Pre-pulling base images (with retry on network errors)"
Warm-Images $baseImages

Step "Rebuilding app image"
Build-Service @("--pull") "app" "Rebuilding the app image failed"

Step "Rebuilding worker image"
Build-Service @("--pull") "worker" "Rebuilding the worker image failed"

Step "Rebuilding beat scheduler image"
Build-Service @() "beat" "Rebuilding the beat image failed"

# --- 4. Migrate ----------------------------------------------------------

Step "Starting database and Redis"
Invoke-Compose @("up", "-d", "db", "redis") "Starting db/redis failed"

Step "Running database migrations"
Invoke-Compose @("run", "--rm", "app", "alembic", "upgrade", "head") "Database migration failed"

# --- 5. Restart the stack -----------------------------------------------

Step "Restarting Wardress services on the new images"
Invoke-Compose @("up", "-d", "--no-build", "app", "worker") "Restarting app/worker failed"

# Beat must ALWAYS be force-recreated: `up -d` does not recreate a
# running container whose own config didn't change, and beat shares the
# worker image - so after a rebuild it would silently keep the old code.
Step "Force-recreating the beat scheduler (required after image rebuilds)"
Invoke-Compose @("up", "-d", "--no-build", "--force-recreate", "beat") "Recreating beat failed"

# Same situation for the optional telegram-bot, but only if it is running.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$botRunning = docker compose --profile telegram ps --status running -q telegram-bot 2>$null
$botQueryOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap
if ($botQueryOk -and $botRunning) {
    Step "Force-recreating the running telegram-bot"
    Invoke-Compose @("--profile", "telegram", "up", "-d", "--no-build", "--force-recreate", "telegram-bot") "Recreating telegram-bot failed"
}

# --- 6. Verify -----------------------------------------------------------

Step "Waiting for the dashboard to come back"

$port = "8321"
foreach ($line in Get-Content $EnvFile) {
    if ($line -match "^WARDRESS_HTTP_PORT=(.+)$") { $port = $Matches[1].Trim() }
}
$dashboardUrl = "http://localhost:$port"

$deadline = (Get-Date).AddSeconds(120)
$healthy = $false
$attempts = 0
while ((Get-Date) -lt $deadline) {
    $attempts++
    $remaining = [int](($deadline - (Get-Date)).TotalSeconds)
    Write-Progress-Inline "Checking health endpoint (attempt $attempts, ${remaining}s remaining)..."
    
    try {
        $resp = Invoke-WebRequest -Uri "$dashboardUrl/api/health/live" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    }
    catch { }
    Start-Sleep -Seconds 3
}
if (-not $healthy) {
    Fail ("The API did not become healthy within 120 seconds after the update. " +
        "Check the logs with: docker compose logs app")
}
Write-Progress-Done "Dashboard is healthy"

Write-Host ""
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host " Wardress updated and running: $dashboardUrl" -ForegroundColor Green
Write-Host " Data, artifacts, and .env were preserved." -ForegroundColor Green
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
exit 0
