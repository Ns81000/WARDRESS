# Shared helpers for the Wardress PowerShell scripts (install / update /
# uninstall). Dot-sourced by each: . "$PSScriptRoot\lib.ps1"
#
# Design rule: NOTHING about images, tags, or registries is hardcoded here.
# The image set is derived at runtime from the actual Dockerfiles and the
# docker-compose config, so the scripts never drift from the real stack.

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
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

function Invoke-WithRetry([scriptblock]$Block, [string]$What, [int]$MaxAttempts = 3, [int]$DelaySeconds = 6) {
    # Run a native/docker command up to $MaxAttempts times, treating a
    # non-zero exit as retryable. Transient registry/DNS/proxy hiccups
    # (ghcr.io token fetch, base-image metadata pulls) are the single most
    # common install failure on real machines; a couple of retries clears
    # nearly all of them without any user action.
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        & $Block
        if ($LASTEXITCODE -eq 0) { return $true }
        if ($attempt -lt $MaxAttempts) {
            Write-Host ("  $What failed (attempt $attempt of $MaxAttempts) - retrying in " +
                "$DelaySeconds" + "s...") -ForegroundColor Yellow
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
    foreach ($img in $Images) {
        if (-not $img) { continue }
        $ok = Invoke-WithRetry { docker pull $img } "Pulling $img"
        if (-not $ok) {
            Write-Host ("  Could not pre-pull $img after retries; the build will try again. " +
                "If builds keep failing to reach ghcr.io / mcr.microsoft.com / docker.io, " +
                "check VPN/proxy/firewall or Docker Desktop's registry settings.") -ForegroundColor Yellow
        }
    }
}

function Build-Service([string[]]$BuildArgs, [string]$Service, [string]$FailureHint) {
    $ok = Invoke-WithRetry { docker compose build @BuildArgs $Service } "Building $Service"
    if (-not $ok) {
        Fail ("$FailureHint after retries. This is almost always a network/registry issue " +
            "(ghcr.io, mcr.microsoft.com, or docker.io unreachable) rather than a code problem. " +
            "Confirm internet access, disable a blocking VPN/proxy/firewall if present, ensure " +
            "Docker Desktop is fully started, then re-run this script - it resumes from cache.")
    }
}
