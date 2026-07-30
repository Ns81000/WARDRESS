# Wardress pre-flight validation script
# Checks all requirements before installation or updates
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\validate.ps1

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot

# Shared helpers
. (Join-Path $PSScriptRoot "lib.ps1")

Set-TotalSteps 8

$script:ValidationErrors = @()
$script:ValidationWarnings = @()

function Add-ValidationError([string]$Message) {
    $script:ValidationErrors += $Message
    Write-Host "    [ERROR] $Message" -ForegroundColor Red
}

function Add-ValidationWarning([string]$Message) {
    $script:ValidationWarnings += $Message
    Write-Host "    [WARN] $Message" -ForegroundColor Yellow
}

function Test-CommandExists([string]$Command) {
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# --- 1. Docker Desktop ---------------------------------------------------

Step "Validating Docker Desktop"

if (-not (Test-CommandExists "docker")) {
    Add-ValidationError "Docker is not installed or not in PATH"
} else {
    Write-Host "    Docker CLI found" -ForegroundColor Green
    
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $dockerVersion = docker --version 2>&1
    $ErrorActionPreference = $prev
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "    Version: $dockerVersion" -ForegroundColor Gray
    }
    
    if (-not (Invoke-Quiet { docker info })) {
        Add-ValidationError "Docker engine is not running - start Docker Desktop"
    } else {
        Write-Host "    Docker engine is running" -ForegroundColor Green
    }
    
    if (-not (Invoke-Quiet { docker compose version })) {
        Add-ValidationError "Docker Compose plugin not available"
    } else {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $composeVersion = docker compose version 2>&1
        $ErrorActionPreference = $prev
        Write-Host "    Compose: $composeVersion" -ForegroundColor Gray
    }
}

# --- 2. Git --------------------------------------------------------------

Step "Validating Git"

if (-not (Test-CommandExists "git")) {
    Add-ValidationWarning "Git not found (optional for manual installs)"
} else {
    $gitVersion = git --version
    Write-Host "    Git found: $gitVersion" -ForegroundColor Green
}

# --- 3. Node.js / pnpm ---------------------------------------------------

Step "Validating Node.js and pnpm"

if (-not (Test-CommandExists "node")) {
    Add-ValidationError "Node.js is not installed - required for frontend builds"
} else {
    $nodeVersion = node --version
    Write-Host "    Node.js: $nodeVersion" -ForegroundColor Green
    
    $majorVersion = [int]($nodeVersion -replace 'v(\d+)\..*', '$1')
    if ($majorVersion -lt 18) {
        Add-ValidationError "Node.js version $nodeVersion is too old - need v18 or higher"
    }
}

if (-not (Test-CommandExists "pnpm")) {
    Add-ValidationWarning "pnpm not found - will attempt auto-install during build"
} else {
    $pnpmVersion = pnpm --version
    Write-Host "    pnpm: $pnpmVersion" -ForegroundColor Green
}

# --- 4. Python (optional, for local development) ------------------------

Step "Validating Python (optional)"

if (-not (Test-CommandExists "python")) {
    Write-Host "    Python not found (optional for local development)" -ForegroundColor Gray
} else {
    $pythonVersion = python --version
    Write-Host "    Python found: $pythonVersion" -ForegroundColor Green
}

# --- 5. Repository structure ---------------------------------------------

Step "Validating repository structure"

Set-Location $RepoRoot

$requiredFiles = @(
    ".env.example",
    "docker-compose.yml",
    "backend\pyproject.toml",
    "backend\Dockerfile.app",
    "backend\Dockerfile.worker",
    "frontend\package.json"
)

foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        Add-ValidationError "Missing required file: $file"
    } else {
        Write-Host "    Found: $file" -ForegroundColor Green
    }
}

# --- 6. Frontend dependencies --------------------------------------------

Step "Validating frontend dependencies"

$frontendPath = Join-Path $RepoRoot "frontend"
if (Test-Path (Join-Path $frontendPath "package.json")) {
    Push-Location $frontendPath
    try {
        if (Test-Path "node_modules") {
            Write-Host "    Frontend dependencies already installed" -ForegroundColor Green
        } else {
            if (Test-CommandExists "pnpm") {
                Write-Host "    Installing frontend dependencies..." -ForegroundColor Cyan
                pnpm install --frozen-lockfile | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "    Dependencies installed successfully" -ForegroundColor Green
                } else {
                    Add-ValidationError "Failed to install frontend dependencies"
                }
            } else {
                Add-ValidationWarning "Cannot install dependencies - pnpm not available"
            }
        }
    } finally {
        Pop-Location
    }
}

# --- 7. TypeScript compilation -------------------------------------------

Step "Validating TypeScript compilation"

if (Test-CompilationErrors $RepoRoot) {
    Write-Host "    TypeScript compilation successful" -ForegroundColor Green
} else {
    Add-ValidationError "TypeScript compilation errors detected"
}

# --- 8. Docker resources -------------------------------------------------

Step "Checking Docker resources"

$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$dockerInfo = docker info --format json 2>&1 | ConvertFrom-Json
$ErrorActionPreference = $prev

if ($dockerInfo) {
    $cpus = $dockerInfo.NCPU
    $memGB = [math]::Round($dockerInfo.MemTotal / 1GB, 1)
    
    Write-Host "    Available CPUs: $cpus" -ForegroundColor Gray
    Write-Host "    Available Memory: $memGB GB" -ForegroundColor Gray
    
    if ($memGB -lt 4) {
        Add-ValidationWarning "Less than 4GB RAM allocated to Docker - builds may be slow"
    }
    
    if ($cpus -lt 2) {
        Add-ValidationWarning "Less than 2 CPUs allocated to Docker - builds may be slow"
    }
}

# --- Summary -------------------------------------------------------------

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "VALIDATION SUMMARY" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

if ($script:ValidationErrors.Count -eq 0 -and $script:ValidationWarnings.Count -eq 0) {
    Write-Host "All checks passed - ready to install Wardress" -ForegroundColor Green
    Write-Host ""
    Write-Host "Run: powershell -ExecutionPolicy Bypass -File scripts\install.ps1" -ForegroundColor Cyan
    exit 0
}

if ($script:ValidationErrors.Count -gt 0) {
    Write-Host "ERRORS ($($script:ValidationErrors.Count)):" -ForegroundColor Red
    foreach ($err in $script:ValidationErrors) {
        Write-Host "  - $err" -ForegroundColor Red
    }
    Write-Host ""
}

if ($script:ValidationWarnings.Count -gt 0) {
    Write-Host "WARNINGS ($($script:ValidationWarnings.Count)):" -ForegroundColor Yellow
    foreach ($warn in $script:ValidationWarnings) {
        Write-Host "  - $warn" -ForegroundColor Yellow
    }
    Write-Host ""
}

if ($script:ValidationErrors.Count -gt 0) {
    Write-Host "Fix the errors above before proceeding with installation." -ForegroundColor Red
    exit 1
} else {
    Write-Host "Warnings detected but installation can proceed." -ForegroundColor Yellow
    Write-Host "Run: powershell -ExecutionPolicy Bypass -File scripts\install.ps1" -ForegroundColor Cyan
    exit 0
}
