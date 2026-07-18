# Wardress installer (Windows, Docker Desktop already installed).
#
# One-command install:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# What it does, in order:
#   1. Verifies Docker Desktop is installed and the engine is running.
#   2. Generates .env from .env.example on first run, replacing every
#      CHANGE_ME value with a cryptographically random secret.
#      Idempotent: an existing .env is NEVER touched.
#   3. Builds the Docker images serially in the foreground.
#   4. Starts db + redis, runs Alembic migrations, starts the stack.
#   5. Seeds the first admin user (idempotent; never resets a password).
#   6. Creates a Desktop shortcut with the Wardress icon.
#   7. Prints the dashboard URL - and, on first install only, the
#      generated admin credentials (exactly once; they are not stored
#      anywhere outside .env).
#
# Safe to re-run at any time. Exits non-zero with a readable message on
# any failure.

[CmdletBinding()]
param(
    # Email for the seeded admin account (only used when .env is first
    # generated; afterwards the value in .env is authoritative).
    [string]$AdminEmail = "admin@example.com"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"
$IconFile = Join-Path $RepoRoot "assets\brand\wardress.ico"

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function New-RandomSecret([int]$Length = 43) {
    # URL- and .env-safe alphabet (alphanumeric only): these values are
    # embedded in DATABASE_URL and parsed by docker compose, so no
    # characters that need quoting or percent-encoding.
    $alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    # Rejection sampling: bytes >= 248 (the largest multiple of 62 under
    # 256) are discarded so every character is uniformly likely.
    # Create()/GetBytes works on both Windows PowerShell 5.1 (.NET
    # Framework) and PowerShell 7+; the static Fill() does not exist on 5.1.
    $limit = [Math]::Floor(256 / $alphabet.Length) * $alphabet.Length
    $sb = [System.Text.StringBuilder]::new()
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $buf = [byte[]]::new(128)
        while ($sb.Length -lt $Length) {
            $rng.GetBytes($buf)
            foreach ($b in $buf) {
                if ($b -lt $limit -and $sb.Length -lt $Length) {
                    [void]$sb.Append($alphabet[$b % $alphabet.Length])
                }
            }
        }
    }
    finally { $rng.Dispose() }
    $sb.ToString()
}

function Invoke-Quiet([scriptblock]$Block) {
    # Probe a native command, discarding all output. Under EAP=Stop,
    # PowerShell 5.1 turns redirected native stderr (even harmless
    # warnings) into terminating errors - relax it around the probe.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Block 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    finally { $ErrorActionPreference = $prev }
}

function Invoke-Compose([string[]]$ComposeArgs, [string]$FailureHint) {
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "$FailureHint (docker compose $($ComposeArgs -join ' ') exited with code $LASTEXITCODE)"
    }
}

# --- 1. Docker Desktop checks -------------------------------------------

Step "Checking Docker Desktop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail ("Docker is not installed (the 'docker' command was not found). " +
        "Wardress requires Docker Desktop: https://www.docker.com/products/docker-desktop/")
}

if (-not (Invoke-Quiet { docker info })) {
    Fail ("Docker Desktop is installed but the engine is not running. " +
        "Start Docker Desktop, wait for it to say 'Engine running', then re-run this script.")
}

if (-not (Invoke-Quiet { docker compose version })) {
    Fail ("The 'docker compose' plugin is unavailable. Update Docker Desktop " +
        "to a current version: https://www.docker.com/products/docker-desktop/")
}

Write-Host "Docker engine is running."

# --- 2. Generate .env (first run only) ----------------------------------

Set-Location $RepoRoot

if (-not (Test-Path $EnvExample)) {
    Fail ".env.example not found at $EnvExample - run this script from a complete Wardress checkout."
}

$FirstInstall = -not (Test-Path $EnvFile)
$GeneratedAdminPassword = $null

if ($FirstInstall) {
    Step "Generating .env with fresh random secrets"

    $dbPassword = New-RandomSecret
    $GeneratedAdminPassword = New-RandomSecret 20
    $freshSecrets = @{}   # var name -> generated value (for non-special lines)

    $outLines = foreach ($line in Get-Content $EnvExample) {
        if ($line -notmatch "CHANGE_ME") {
            $line
            continue
        }
        if ($line -match "^([A-Za-z_][A-Za-z0-9_]*)=") {
            $name = $Matches[1]
            switch ($name) {
                "POSTGRES_PASSWORD" { "POSTGRES_PASSWORD=$dbPassword" }
                "DATABASE_URL" {
                    # Must carry the same password as POSTGRES_PASSWORD.
                    $line -replace "CHANGE_ME[A-Z_]*", $dbPassword
                }
                "ADMIN_PASSWORD" { "ADMIN_PASSWORD=$GeneratedAdminPassword" }
                "ADMIN_EMAIL" { "ADMIN_EMAIL=$AdminEmail" }
                default {
                    # Any other CHANGE_ME marker gets its own fresh secret
                    # (covers JWT_SECRET, CREDENTIALS_ENCRYPTION_KEY, and
                    # any future additions to .env.example).
                    if (-not $freshSecrets.ContainsKey($name)) {
                        $freshSecrets[$name] = New-RandomSecret
                    }
                    $line -replace "CHANGE_ME[A-Z_]*", $freshSecrets[$name]
                }
            }
        }
        else {
            $line
        }
    }

    # Honor the -AdminEmail parameter even though the example line has no
    # CHANGE_ME marker on it.
    $outLines = $outLines | ForEach-Object {
        if ($_ -match "^ADMIN_EMAIL=") { "ADMIN_EMAIL=$AdminEmail" } else { $_ }
    }

    # UTF-8 without BOM, LF line endings.
    [System.IO.File]::WriteAllText($EnvFile, (($outLines -join "`n") + "`n"),
        [System.Text.UTF8Encoding]::new($false))

    # Comments may mention CHANGE_ME; only assignment lines matter.
    if (Select-String -Path $EnvFile -Pattern "^[A-Za-z_][A-Za-z0-9_]*=.*CHANGE_ME" -Quiet) {
        Remove-Item $EnvFile
        Fail "Internal error: a CHANGE_ME marker survived .env generation. No .env was left behind; please report this."
    }

    Write-Host ".env written (gitignored; secrets live only in this file)."
}
else {
    Step "Existing .env found - keeping it untouched"
    if (Select-String -Path $EnvFile -Pattern "^[A-Za-z_][A-Za-z0-9_]*=.*CHANGE_ME" -Quiet) {
        Fail (".env still contains CHANGE_ME placeholder values. It was not generated by this installer. " +
            "Move it aside (e.g. rename to .env.bak) and re-run to generate real secrets.")
    }
}

# Read the values this script itself needs (port for the URL, email for
# the summary). Never read or print the secrets.
$envMap = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
        $envMap[$Matches[1]] = $Matches[2]
    }
}
$port = if ($envMap.ContainsKey("WARDRESS_HTTP_PORT") -and $envMap["WARDRESS_HTTP_PORT"]) {
    $envMap["WARDRESS_HTTP_PORT"]
} else { "8321" }
$adminEmailEffective = if ($envMap.ContainsKey("ADMIN_EMAIL") -and $envMap["ADMIN_EMAIL"]) {
    $envMap["ADMIN_EMAIL"]
} else { $AdminEmail }
$dashboardUrl = "http://localhost:$port"

# --- 3. Build images (serially, in the foreground) ----------------------

Step "Building the app image (API + dashboard) - first build takes a few minutes"
Invoke-Compose @("build", "app") "Building the app image failed"

Step "Building the worker image (browser + detection engine) - the largest image"
Invoke-Compose @("build", "worker") "Building the worker image failed"

Step "Building the scheduler image (shares the worker build cache)"
Invoke-Compose @("build", "beat") "Building the beat image failed"

# --- 4. Start db/redis, migrate, start the stack ------------------------

Step "Starting database and Redis"
Invoke-Compose @("up", "-d", "db", "redis") "Starting db/redis failed"

Step "Running database migrations"
Invoke-Compose @("run", "--rm", "app", "alembic", "upgrade", "head") "Database migration failed"

Step "Starting the Wardress services"
Invoke-Compose @("up", "-d", "--no-build", "app", "worker", "beat") "Starting the stack failed"

Step "Waiting for the dashboard to come up"
$deadline = (Get-Date).AddSeconds(120)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "$dashboardUrl/api/health/live" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    }
    catch { }
    Start-Sleep -Seconds 3
}
if (-not $healthy) {
    Fail ("The API did not become healthy within 120 seconds. " +
        "Check the logs with: docker compose logs app")
}
Write-Host "Dashboard is up."

# --- 5. Seed the admin user ---------------------------------------------

Step "Seeding the admin user (idempotent)"
docker compose exec -T app python -m app.seed_admin
if ($LASTEXITCODE -ne 0) {
    Fail "Admin seeding failed - check ADMIN_EMAIL / ADMIN_PASSWORD in .env (password must be at least 12 characters)."
}

# --- 6. Desktop shortcut -------------------------------------------------

Step "Creating the Desktop shortcut"
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $desktop "Wardress.lnk"))
    $shortcut.TargetPath = "explorer.exe"
    $shortcut.Arguments = $dashboardUrl
    $shortcut.Description = "Open the Wardress dashboard"
    if (Test-Path $IconFile) { $shortcut.IconLocation = "$IconFile,0" }
    $shortcut.Save()
    Write-Host "Shortcut created: $desktop\Wardress.lnk"
}
catch {
    # A failed shortcut must not fail the install - everything else works.
    Write-Host "Could not create the Desktop shortcut ($($_.Exception.Message)); open $dashboardUrl directly." -ForegroundColor Yellow
}

# --- 7. Summary ----------------------------------------------------------

Write-Host ""
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host " Wardress is running - open the shortcut on your Desktop, or:" -ForegroundColor Green
Write-Host "   $dashboardUrl" -ForegroundColor Green
Write-Host ""
if ($FirstInstall) {
    Write-Host " Sign in with the generated admin account:" -ForegroundColor Green
    Write-Host "   Email:    $adminEmailEffective"
    Write-Host "   Password: $GeneratedAdminPassword"
    Write-Host ""
    Write-Host " This password is shown ONCE. It is stored only in .env" -ForegroundColor Yellow
    Write-Host " (ADMIN_PASSWORD) - change it after first login, or keep" -ForegroundColor Yellow
    Write-Host " .env safe." -ForegroundColor Yellow
}
else {
    Write-Host " Existing install detected: credentials were not changed." -ForegroundColor Green
    Write-Host " Sign in as $adminEmailEffective with your existing password."
}
Write-Host ""
Write-Host " Optional services:"
Write-Host "   Telegram bot:  docker compose --profile telegram up -d"
Write-Host "   Local LLM:     docker compose --profile ollama up -d"
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
exit 0
