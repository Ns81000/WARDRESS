# Shared helpers for the Wardress PowerShell scripts (install / update /
# uninstall). Dot-sourced by each: . "$PSScriptRoot\lib.ps1"
#
# Design rule: NOTHING about images, tags, or registries is hardcoded here.
# The image set is derived at runtime from the actual Dockerfiles and the
# docker-compose config, so the scripts never drift from the real stack.

$script:ProgressPreference = 'SilentlyContinue'
$script:TotalSteps = 0
$script:CurrentStep = 0

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Step([string]$Message) {
    $script:CurrentStep++
    Write-Host ""
    if ($script:TotalSteps -gt 0) {
        $percent = [int](($script:CurrentStep / $script:TotalSteps) * 100)
        Write-Host "[$script:CurrentStep/$script:TotalSteps - $percent%] ==> $Message" -ForegroundColor Cyan
    } else {
        Write-Host "==> $Message" -ForegroundColor Cyan
    }
}

function Set-TotalSteps([int]$Total) {
    $script:TotalSteps = $Total
    $script:CurrentStep = 0
}

function Write-Progress-Inline([string]$Message, [string]$Color = "Gray") {
    Write-Host "    $Message" -ForegroundColor $Color -NoNewline
    Write-Host "`r" -NoNewline
}

function Write-Progress-Done([string]$Message = "Done") {
    Write-Host "    $Message" -ForegroundColor Green
}

function Invoke-Quiet([scriptblock]$Block) {
    # Probe a native command, discarding all output. Under EAP=Stop,
    # PowerShell 5.1 turns redirected native stderr (even harmless
    # warnings) into terminating errors - relax it around the probe.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $null = & $Block 2>&1
        return ($LASTEXITCODE -eq 0)
    }
    finally { $ErrorActionPreference = $prev }
}

function Invoke-Compose([string[]]$ComposeArgs, [string]$FailureHint) {
    Write-Host "    Running: docker compose $($ComposeArgs -join ' ')" -ForegroundColor DarkGray
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "$FailureHint (docker compose $($ComposeArgs -join ' ') exited with code $LASTEXITCODE)"
    }
}

function Test-CompilationErrors([string]$RepoRoot) {
    # Pre-flight TypeScript check to fail fast before Docker build
    $frontendPath = Join-Path $RepoRoot "frontend"
    if (-not (Test-Path $frontendPath)) { return $true }
    
    Push-Location $frontendPath
    try {
        Write-Progress-Inline "Checking TypeScript compilation..."
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $output = pnpm run type-check 2>&1
        $ok = $LASTEXITCODE -eq 0
        $ErrorActionPreference = $prev
        
        if ($ok) {
            Write-Progress-Done "TypeScript check passed"
            return $true
        } else {
            Write-Host ""
            Write-Host "TypeScript compilation errors detected:" -ForegroundColor Red
            Write-Host $output -ForegroundColor Yellow
            return $false
        }
    } finally {
        Pop-Location
    }
}

function Invoke-WithRetry([scriptblock]$Block, [string]$What, [int]$MaxAttempts = 3, [int]$DelaySeconds = 6) {
    # Run a native/docker command up to $MaxAttempts times, treating a
    # non-zero exit as retryable. Transient registry/DNS/proxy hiccups
    # (ghcr.io token fetch, base-image metadata pulls) are the single most
    # common install failure on real machines; a couple of retries clears
    # nearly all of them without any user action.
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        
        # Check if this is a compilation error (not retryable)
        $output = & $Block 2>&1
        $isCompilationError = $output -match "error TS\d+" -or $output -match "ELIFECYCLE"
        
        $ErrorActionPreference = $prev
        
        if ($LASTEXITCODE -eq 0) { 
            return $true 
        }
        
        if ($isCompilationError) {
            Write-Host ""
            Write-Host "Compilation error detected (not retryable):" -ForegroundColor Red
            Write-Host $output -ForegroundColor Yellow
            return $false
        }
        
        if ($attempt -lt $MaxAttempts) {
            Write-Host "  $What failed (attempt $attempt of $MaxAttempts) - retrying in $DelaySeconds`s..." -ForegroundColor Yellow
            Start-Sleep -Seconds $DelaySeconds
            $DelaySeconds = [Math]::Min($DelaySeconds * 2, 30)
        }
    }
    return $false
}

function Get-BuildBaseImages([string]$RepoRoot) {
    # Parse every backend/Dockerfile.* for the external images its build
    # depends on: `FROM <ref>` bases and `COPY --from=<ref>` stages. Named
    # local build stages (FROM ... AS <name>, and COPY --from=<name>) are
    # excluded - only real registry references are returned.
    $images = [System.Collections.Generic.List[string]]::new()
    $dockerfiles = Get-ChildItem -Path (Join-Path $RepoRoot "backend") -Filter "Dockerfile.*" -File -ErrorAction SilentlyContinue
    foreach ($df in $dockerfiles) {
        $lines = Get-Content $df.FullName
        $stages = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        # First pass: collect local stage aliases (FROM ... AS <alias>).
        foreach ($line in $lines) {
            if ($line -match "^\s*FROM\s+(?:--\S+\s+)*\S+\s+AS\s+(\S+)") {
                [void]$stages.Add($Matches[1])
            }
        }
        # Second pass: collect external refs that are not local stages.
        foreach ($line in $lines) {
            if ($line -match "^\s*FROM\s+(?:--\S+\s+)*(\S+)") {
                $ref = $Matches[1]
                if (-not $stages.Contains($ref) -and -not $images.Contains($ref)) { $images.Add($ref) }
            }
            if ($line -match "--from=(\S+)") {
                $ref = $Matches[1]
                # Only registry-shaped refs (a stage name has no ':' or '/').
                if (($ref -match "[:/]") -and -not $stages.Contains($ref) -and -not $images.Contains($ref)) {
                    $images.Add($ref)
                }
            }
        }
    }
    return $images.ToArray()
}

function Get-ComposeRemoteImages([string[]]$Profiles = @()) {
    # Images that docker-compose PULLS (services with an `image:` and no
    # `build:`) - db, redis, and (with the profile) ollama. Built services
    # are excluded so we never try to `docker pull wardress-app`. Derived
    # from `docker compose config`, so it always matches the compose file.
    $profileArgs = @()
    foreach ($p in $Profiles) { $profileArgs += @("--profile", $p) }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $json = & docker compose @profileArgs config --format json 2>$null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    if (-not $ok -or -not $json) { return @() }
    try { $cfg = $json | ConvertFrom-Json } catch { return @() }
    $images = [System.Collections.Generic.List[string]]::new()
    if ($cfg.PSObject.Properties.Name -contains "services") {
        foreach ($svc in $cfg.services.PSObject.Properties) {
            $v = $svc.Value
            $hasImage = ($v.PSObject.Properties.Name -contains "image") -and $v.image
            $hasBuild = ($v.PSObject.Properties.Name -contains "build") -and $v.build
            if ($hasImage -and -not $hasBuild) {
                if (-not $images.Contains($v.image)) { $images.Add($v.image) }
            }
        }
    }
    return $images.ToArray()
}

function Get-ComposeServiceImage([string]$Service) {
    # The resolved image ref for one service (used to reuse an already-present
    # image as a throwaway tar helper instead of pulling a new one).
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $json = & docker compose config --format json 2>$null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    if (-not $ok -or -not $json) { return $null }
    try { $cfg = $json | ConvertFrom-Json } catch { return $null }
    if ($cfg.PSObject.Properties.Name -contains "services") {
        $svc = $cfg.services.PSObject.Properties | Where-Object { $_.Name -eq $Service } | Select-Object -First 1
        if ($svc -and ($svc.Value.PSObject.Properties.Name -contains "image")) { return $svc.Value.image }
    }
    return $null
}

function Warm-Images([string[]]$Images) {
    # Best-effort: pull each image with retries so a transient registry
    # error warms the cache instead of aborting a multi-minute build.
    $total = $Images.Length
    $current = 0
    
    foreach ($img in $Images) {
        if (-not $img) { continue }
        $current++
        
        Write-Progress-Inline "Pulling base image $current/$total`: $img"
        $ok = Invoke-WithRetry { docker pull $img *>&1 | Out-Null } "Pulling $img" 2
        
        if ($ok) {
            Write-Host "    [$current/$total] Pulled: $img" -ForegroundColor Green
        } else {
            Write-Host "    [$current/$total] Failed: $img (will retry during build)" -ForegroundColor Yellow
        }
    }
    
    if ($total -gt 0) {
        Write-Progress-Done "Pulled $current/$total base images"
    }
}

function Build-Service([string[]]$BuildArgs, [string]$Service, [string]$FailureHint) {
    Write-Host "    Building $Service..." -ForegroundColor Cyan
    
    # Stream build output with progress indicators
    $buildCmd = "docker"
    $fullArgs = @("compose", "build") + $BuildArgs + @($Service)
    
    $startTime = Get-Date
    $process = Start-Process -FilePath $buildCmd -ArgumentList $fullArgs `
        -NoNewWindow -PassThru -RedirectStandardOutput "build_$Service.log" `
        -RedirectStandardError "build_$Service.err.log"
    
    $spinChars = @('|', '/', '-', '\')
    $spinIndex = 0
    
    while (-not $process.HasExited) {
        $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
        $spin = $spinChars[$spinIndex % 4]
        Write-Host "`r    Building $Service... $spin ($elapsed`s elapsed)" -NoNewline -ForegroundColor Cyan
        $spinIndex++
        Start-Sleep -Milliseconds 250
    }
    
    $elapsed = [int]((Get-Date) - $startTime).TotalSeconds
    Write-Host "`r" -NoNewline
    
    if ($process.ExitCode -eq 0) {
        Write-Host "    Built $Service successfully ($elapsed`s)" -ForegroundColor Green
        Remove-Item "build_$Service.log" -ErrorAction SilentlyContinue
        Remove-Item "build_$Service.err.log" -ErrorAction SilentlyContinue
        return $true
    } else {
        Write-Host "    Build failed for $Service" -ForegroundColor Red
        
        # Show error details
        if (Test-Path "build_$Service.err.log") {
            $errorContent = Get-Content "build_$Service.err.log" -Raw
            if ($errorContent) {
                Write-Host ""
                Write-Host "Build error output:" -ForegroundColor Red
                Write-Host $errorContent -ForegroundColor Yellow
            }
        }
        
        Fail ("$FailureHint. Build took $elapsed`s. Check build_$Service.log for details.")
    }
}
