# Wardress uninstaller (Windows, Docker Desktop).
#
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
#
# What it does, in order:
#   1. Verifies Docker Desktop is running.
#   2. Backs up everything recoverable to a timestamped folder (unless
#      -SkipBackup): your .env, a logical Postgres dump (pg_dump), and the
#      scan-artifacts volume (tar.gz). Nothing is deleted until the backup
#      has completed.
#   3. Removes the whole Wardress footprint from Docker: containers,
#      networks, named volumes (db-data, redis-data, scan-artifacts,
#      ollama-data), and the locally-built images.
#   4. Removes the Desktop shortcut.
#   5. Prints where the backup is and how to restore it.
#
# The repository files on disk are left in place - delete the folder
# yourself if you also want the source gone. Exits non-zero with a
# readable message on any failure.

[CmdletBinding()]
param(
    # Skip the confirmation prompt (for scripted/unattended teardown).
    [switch]$Force,
    # Skip the data backup entirely (containers/volumes/images still removed).
    [switch]$SkipBackup,
    # Where to write the backup. Defaults to a timestamped folder next to
    # the repo. The timestamp is filesystem-safe (no colons).
    [string]$BackupPath,
    # Leave the locally-built Wardress images in place (only remove
    # containers, networks, and volumes).
    [switch]$KeepImages,
    # Also remove the pulled upstream base images (postgres, redis, uv,
    # playwright, node, ollama). Off by default because these are shared,
    # reusable, and slow to re-pull; pass this for a full-footprint wipe.
    [switch]$PruneBaseImages
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $RepoRoot ".env"
$Project = "wardress"   # docker-compose.yml `name:` - volumes are $Project_<vol>

# Shared helpers (Fail/Step/Invoke-*, dynamic image discovery).
. (Join-Path $PSScriptRoot "lib.ps1")

# --- 1. Preconditions ----------------------------------------------------

Step "Checking Docker Desktop"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail ("Docker is not installed (the 'docker' command was not found). " +
        "There is nothing for this script to remove.")
}
if (-not (Invoke-Quiet { docker info })) {
    Fail ("Docker Desktop is installed but the engine is not running. " +
        "Start Docker Desktop, wait for 'Engine running', then re-run this script.")
}

Set-Location $RepoRoot

# --- 2. Confirm ----------------------------------------------------------

if (-not $Force) {
    Write-Host ""
    Write-Host "This will REMOVE Wardress from Docker:" -ForegroundColor Yellow
    Write-Host "  - all Wardress containers (app, worker, beat, telegram-bot, db, redis, ollama)"
    Write-Host "  - the Wardress network"
    Write-Host "  - the data volumes (database, redis, scan artifacts, ollama models)"
    if (-not $KeepImages) { Write-Host "  - the locally-built Wardress images" }
    if ($PruneBaseImages) { Write-Host "  - the pulled base images (postgres, redis, uv, playwright, node, ollama)" }
    if (-not $SkipBackup) {
        Write-Host ""
        Write-Host "A backup (.env + database dump + scan artifacts) is taken FIRST." -ForegroundColor Green
    }
    else {
        Write-Host ""
        Write-Host "-SkipBackup was passed: NO backup will be taken. Data loss is permanent." -ForegroundColor Red
    }
    Write-Host ""
    $answer = Read-Host "Type 'yes' to proceed"
    if ($answer -ne "yes") {
        Write-Host "Aborted - nothing was changed." -ForegroundColor Green
        exit 0
    }
}

# --- 3. Backup -----------------------------------------------------------

$backupDir = $null
if (-not $SkipBackup) {
    # Filesystem-safe timestamp (no colons); avoids Get-Date format pitfalls.
    $stamp = (Get-Date).ToString("yyyy-MM-dd_HH-mm-ss")
    if ($BackupPath) {
        $backupDir = $BackupPath
    }
    else {
        $backupDir = Join-Path (Split-Path -Parent $RepoRoot) "wardress-backup-$stamp"
    }
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Step "Backing up to: $backupDir"

    # 3a. .env (holds every secret + admin credentials).
    if (Test-Path $EnvFile) {
        Copy-Item $EnvFile (Join-Path $backupDir ".env") -Force
        Write-Host "  Saved .env"
    }
    else {
        Write-Host "  No .env found - skipping (nothing to save)." -ForegroundColor Yellow
    }

    # Read DB user/name for the dump (defaults match docker-compose.yml).
    $pgUser = "wardress"; $pgDb = "wardress"
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content $EnvFile) {
            if ($line -match "^POSTGRES_USER=(.*)$") { $pgUser = $Matches[1].Trim() }
            elseif ($line -match "^POSTGRES_DB=(.*)$") { $pgDb = $Matches[1].Trim() }
        }
    }

    # 3b. Postgres logical dump. Bring db up (safe if already running),
    # wait for readiness, then pg_dump through the running container.
    Step "Backing up the database (pg_dump)"
    if (Invoke-Quiet { docker compose up -d db }) {
        $ready = $false
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            if (Invoke-Quiet { docker compose exec -T db pg_isready -U $pgUser -d $pgDb }) {
                $ready = $true; break
            }
            Start-Sleep -Seconds 2
        }
        if ($ready) {
            $dumpFile = Join-Path $backupDir "database.sql"
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            # --clean --if-exists makes the dump safely re-runnable on restore.
            docker compose exec -T db pg_dump -U $pgUser --clean --if-exists $pgDb `
                > $dumpFile 2>$null
            $dumpOk = ($LASTEXITCODE -eq 0)
            $ErrorActionPreference = $prev
            if ($dumpOk -and (Test-Path $dumpFile) -and (Get-Item $dumpFile).Length -gt 0) {
                Write-Host "  Saved database.sql"
            }
            else {
                Write-Host "  Database dump did not complete - the DB may already be gone. Continuing." -ForegroundColor Yellow
                if (Test-Path $dumpFile) { Remove-Item $dumpFile -ErrorAction SilentlyContinue }
            }
        }
        else {
            Write-Host "  Database did not become ready in time - skipping the dump." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "  Could not start the database container - skipping the dump." -ForegroundColor Yellow
    }

    # 3c. Scan-artifacts volume (screenshots/HTML). Tar it out via a
    # throwaway container mounting the named volume read-only. Reuse the
    # db service's own image (already present locally, and it has tar) so
    # the uninstaller never pulls a new image just to make a backup. The
    # image ref is discovered from compose config - nothing hardcoded.
    Step "Backing up scan artifacts"
    $artVol = "${Project}_scan-artifacts"
    $helperImage = Get-ComposeServiceImage "db"
    if (Invoke-Quiet { docker volume inspect $artVol }) {
        if (-not $helperImage) {
            Write-Host "  Could not resolve a helper image from compose config - skipping artifact archive." -ForegroundColor Yellow
        }
        else {
            $prev = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $srcMount = $artVol + ":/data:ro"
            $dstMount = $backupDir + ":/backup"
            docker run --rm -v $srcMount -v $dstMount --entrypoint tar $helperImage `
                czf /backup/scan-artifacts.tar.gz -C /data . 2>$null
            $tarOk = ($LASTEXITCODE -eq 0)
            $ErrorActionPreference = $prev
            if ($tarOk) { Write-Host "  Saved scan-artifacts.tar.gz" }
            else { Write-Host "  Could not archive scan artifacts - continuing." -ForegroundColor Yellow }
        }
    }
    else {
        Write-Host "  No scan-artifacts volume found - skipping." -ForegroundColor Yellow
    }

    # 3d. A short restore note so the backup is self-describing.
    $readme = @"
Wardress backup - $stamp
=========================

Contents:
  .env                    Your configuration and secrets (admin password, JWT/
                          encryption keys, DB password). Keep this file safe.
  database.sql            Logical Postgres dump (pg_dump --clean --if-exists).
  scan-artifacts.tar.gz   Stored screenshots and captured HTML.

To restore into a fresh install:
  1. Reinstall Wardress but BEFORE first run, copy this .env back into the
     repo root (so the same DB password / keys are used):
        copy "$backupDir\.env" "<repo>\.env"
  2. Start the stack once so the database exists:
        powershell -ExecutionPolicy Bypass -File scripts\install.ps1
  3. Restore the database:
        Get-Content "$backupDir\database.sql" | docker compose exec -T db psql -U $pgUser -d $pgDb
  4. Restore artifacts into the volume (the db image is already present
     after step 2, so this pulls nothing new):
        docker run --rm -v ${Project}_scan-artifacts:/data -v "${backupDir}:/backup" --entrypoint tar $helperImage xzf /backup/scan-artifacts.tar.gz -C /data
  5. Restart:
        docker compose up -d
"@
    Set-Content -Path (Join-Path $backupDir "RESTORE.txt") -Value $readme -Encoding UTF8
    Write-Host "  Wrote RESTORE.txt"
}

# --- 4. Tear down Docker resources --------------------------------------

Step "Removing Wardress containers, network, and volumes"
# --profile flags so profiled services (telegram-bot, ollama) are included.
# -v removes named volumes; --remove-orphans sweeps any stragglers.
$downArgs = @("--profile", "telegram", "--profile", "ollama", "down", "-v", "--remove-orphans")
if (-not $KeepImages) { $downArgs += @("--rmi", "local") }
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& docker compose @downArgs
$downExit = $LASTEXITCODE
$ErrorActionPreference = $prev
if ($downExit -ne 0) {
    Write-Host ("  'docker compose down' returned $downExit - some resources may already be gone. " +
        "Continuing to a best-effort sweep.") -ForegroundColor Yellow
}

# Best-effort sweep of the named volumes in case a non-standard project
# name or an interrupted prior run left them behind.
foreach ($vol in @("db-data", "redis-data", "scan-artifacts", "ollama-data")) {
    $full = "${Project}_$vol"
    if (Invoke-Quiet { docker volume inspect $full }) {
        [void](Invoke-Quiet { docker volume rm $full })
    }
}

# --- 4b. Optionally remove the pulled base images -----------------------
#
# `docker compose down --rmi local` only removes images BUILT by compose
# (wardress-app/worker/beat). The upstream base images pulled from
# registries (postgres, redis, the uv/playwright/node build bases, and
# ollama) are shared/reusable and are left by default. -PruneBaseImages
# removes them too, for a full-footprint wipe. The image set is discovered
# dynamically from the Dockerfiles + compose config - nothing hardcoded.
if ($PruneBaseImages) {
    Step "Removing pulled base images (-PruneBaseImages)"
    $baseImages = @()
    $baseImages += Get-BuildBaseImages $RepoRoot
    $baseImages += Get-ComposeRemoteImages @("telegram", "ollama")
    foreach ($img in ($baseImages | Select-Object -Unique)) {
        if (Invoke-Quiet { docker image inspect $img }) {
            if (Invoke-Quiet { docker rmi $img }) {
                Write-Host "  Removed $img"
            }
            else {
                Write-Host "  Kept $img (still in use by another project or has dependents)." -ForegroundColor Yellow
            }
        }
    }
}

# --- 5. Remove the Desktop shortcut -------------------------------------

Step "Removing the Desktop shortcut"
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $lnk = Join-Path $desktop "Wardress.lnk"
    if (Test-Path $lnk) {
        Remove-Item $lnk -Force
        Write-Host "  Removed $lnk"
    }
    else {
        Write-Host "  No Desktop shortcut found."
    }
}
catch {
    Write-Host "  Could not remove the Desktop shortcut ($($_.Exception.Message))." -ForegroundColor Yellow
}

# --- 6. Summary ----------------------------------------------------------

Write-Host ""
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
Write-Host " Wardress has been removed from Docker." -ForegroundColor Green
if ($backupDir) {
    Write-Host " Backup saved to:" -ForegroundColor Green
    Write-Host "   $backupDir"
    Write-Host " See RESTORE.txt in that folder to bring it back."
}
elseif ($SkipBackup) {
    Write-Host " No backup was taken (-SkipBackup)." -ForegroundColor Yellow
}
Write-Host ""
Write-Host " The repository files are still on disk. Delete the folder"
Write-Host " manually if you want the source gone as well."
if (-not $PruneBaseImages) {
    Write-Host ""
    Write-Host " Shared base images (postgres, redis, uv, playwright, node) were" -ForegroundColor DarkGray
    Write-Host " kept for reuse. Re-run with -PruneBaseImages to remove those too." -ForegroundColor DarkGray
}
Write-Host "----------------------------------------------------------------" -ForegroundColor Green
exit 0
