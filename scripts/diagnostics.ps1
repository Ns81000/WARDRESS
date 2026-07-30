# Wardress diagnostics script
# Collects system information and logs for troubleshooting
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\diagnostics.ps1

[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

if (-not $OutputPath) {
    $OutputPath = Join-Path $RepoRoot "diagnostics_$timestamp.txt"
}

function Write-Section([string]$Title) {
    ""
    "=" * 70
    $Title
    "=" * 70
    ""
}

Write-Host "Collecting diagnostics..." -ForegroundColor Cyan
Write-Host "Output file: $OutputPath" -ForegroundColor Gray

$output = @()

# --- System Information --------------------------------------------------

$output += Write-Section "SYSTEM INFORMATION"
$output += "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$output += "PowerShell Version: $($PSVersionTable.PSVersion)"
$output += "OS: $([System.Environment]::OSVersion.VersionString)"
$output += "Machine: $env:COMPUTERNAME"
$output += "User: $env:USERNAME"
$output += ""

# --- Installed Tools -----------------------------------------------------

$output += Write-Section "INSTALLED TOOLS"

$tools = @{
    "Docker" = "docker --version"
    "Docker Compose" = "docker compose version"
    "Node.js" = "node --version"
    "pnpm" = "pnpm --version"
    "Git" = "git --version"
    "Python" = "python --version"
}

foreach ($tool in $tools.GetEnumerator()) {
    try {
        $version = Invoke-Expression $tool.Value 2>&1
        $output += "$($tool.Key): $version"
    } catch {
        $output += "$($tool.Key): Not found"
    }
}

$output += ""

# --- Docker Status -------------------------------------------------------

$output += Write-Section "DOCKER STATUS"

try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        $output += "Docker engine is running"
        $output += ""
        $output += "Docker Info:"
        $output += $dockerInfo
    } else {
        $output += "Docker engine is not running"
        $output += $dockerInfo
    }
} catch {
    $output += "Error checking Docker: $($_.Exception.Message)"
}

$output += ""

# --- Docker Compose Services ---------------------------------------------

$output += Write-Section "DOCKER COMPOSE SERVICES"

Set-Location $RepoRoot

try {
    $services = docker compose ps --all 2>&1
    if ($LASTEXITCODE -eq 0) {
        $output += $services
    } else {
        $output += "Error listing services:"
        $output += $services
    }
} catch {
    $output += "Error: $($_.Exception.Message)"
}

$output += ""

# --- Docker Images -------------------------------------------------------

$output += Write-Section "DOCKER IMAGES"

try {
    $images = docker images --filter "reference=wardress*" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $output += $images
    } else {
        $output += "Error listing images:"
        $output += $images
    }
} catch {
    $output += "Error: $($_.Exception.Message)"
}

$output += ""

# --- Docker Volumes ------------------------------------------------------

$output += Write-Section "DOCKER VOLUMES"

try {
    $volumes = docker volume ls --filter "name=wardress" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $output += $volumes
    } else {
        $output += "Error listing volumes:"
        $output += $volumes
    }
} catch {
    $output += "Error: $($_.Exception.Message)"
}

$output += ""

# --- Container Logs (last 50 lines each) ---------------------------------

$containers = @("app", "worker", "beat", "db", "redis")

foreach ($container in $containers) {
    $output += Write-Section "LOGS: $container (last 50 lines)"
    try {
        $logs = docker compose logs --tail=50 $container 2>&1
        if ($LASTEXITCODE -eq 0) {
            $output += $logs
        } else {
            $output += "Container not found or not running"
        }
    } catch {
        $output += "Error: $($_.Exception.Message)"
    }
    $output += ""
}

# --- Environment File Check ----------------------------------------------

$output += Write-Section "ENVIRONMENT FILE"

$envFile = Join-Path $RepoRoot ".env"
if (Test-Path $envFile) {
    $output += ".env exists: Yes"
    
    # Check for CHANGE_ME without showing actual secrets
    $hasPlaceholders = Select-String -Path $envFile -Pattern "^[A-Za-z_][A-Za-z0-9_]*=.*CHANGE_ME" -Quiet
    if ($hasPlaceholders) {
        $output += "Has CHANGE_ME placeholders: YES (needs regeneration)"
    } else {
        $output += "Has CHANGE_ME placeholders: No"
    }
    
    # Count lines without revealing contents
    $lineCount = (Get-Content $envFile).Count
    $output += "Lines in .env: $lineCount"
} else {
    $output += ".env exists: No (run install.ps1 first)"
}

$output += ""

# --- Frontend Status -----------------------------------------------------

$output += Write-Section "FRONTEND STATUS"

$frontendPath = Join-Path $RepoRoot "frontend"
if (Test-Path (Join-Path $frontendPath "package.json")) {
    $output += "package.json exists: Yes"
    
    if (Test-Path (Join-Path $frontendPath "node_modules")) {
        $output += "node_modules exists: Yes"
        
        # Try TypeScript check
        Push-Location $frontendPath
        try {
            $output += ""
            $output += "Running TypeScript check..."
            $tsCheck = pnpm run type-check 2>&1
            if ($LASTEXITCODE -eq 0) {
                $output += "TypeScript compilation: SUCCESS"
            } else {
                $output += "TypeScript compilation: FAILED"
                $output += $tsCheck
            }
        } catch {
            $output += "Error running TypeScript check: $($_.Exception.Message)"
        } finally {
            Pop-Location
        }
    } else {
        $output += "node_modules exists: No (run pnpm install)"
    }
} else {
    $output += "package.json not found"
}

$output += ""

# --- Health Check --------------------------------------------------------

$output += Write-Section "HEALTH CHECK"

$envMap = @{}
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $envMap[$Matches[1]] = $Matches[2].Trim()
        }
    }
}

$port = if ($envMap.ContainsKey("WARDRESS_HTTP_PORT")) { $envMap["WARDRESS_HTTP_PORT"] } else { "8321" }
$healthUrl = "http://localhost:$port/api/health/live"
$dashboardUrl = "http://localhost:$port"

try {
    $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5 2>&1
    if ($resp.StatusCode -eq 200) {
        $output += "Health endpoint: OK ($healthUrl)"
    } else {
        $output += "Health endpoint: FAILED (status $($resp.StatusCode))"
    }
} catch {
    $output += "Health endpoint: UNREACHABLE ($healthUrl)"
    $output += "Error: $($_.Exception.Message)"
}

try {
    $resp = Invoke-WebRequest -Uri $dashboardUrl -UseBasicParsing -TimeoutSec 5 2>&1
    if ($resp.StatusCode -eq 200) {
        $output += "Dashboard: ACCESSIBLE ($dashboardUrl)"
    } else {
        $output += "Dashboard: FAILED (status $($resp.StatusCode))"
    }
} catch {
    $output += "Dashboard: UNREACHABLE ($dashboardUrl)"
}

$output += ""

# --- Disk Space ----------------------------------------------------------

$output += Write-Section "DISK SPACE"

try {
    $drive = (Get-Item $RepoRoot).PSDrive.Name + ":"
    $disk = Get-PSDrive $drive.TrimEnd(':')
    $freeGB = [math]::Round($disk.Free / 1GB, 2)
    $usedGB = [math]::Round($disk.Used / 1GB, 2)
    $totalGB = [math]::Round(($disk.Free + $disk.Used) / 1GB, 2)
    
    $output += "Drive: $drive"
    $output += "Free: $freeGB GB"
    $output += "Used: $usedGB GB"
    $output += "Total: $totalGB GB"
    
    if ($freeGB -lt 10) {
        $output += ""
        $output += "WARNING: Less than 10GB free - may cause issues"
    }
} catch {
    $output += "Error checking disk space: $($_.Exception.Message)"
}

$output += ""

# --- Write Output --------------------------------------------------------

$output | Out-File -FilePath $OutputPath -Encoding UTF8

Write-Host ""
Write-Host "Diagnostics collected successfully" -ForegroundColor Green
Write-Host "Output saved to: $OutputPath" -ForegroundColor Cyan
Write-Host ""
Write-Host "Share this file when requesting support." -ForegroundColor Yellow
