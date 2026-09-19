# Audit Phase 4F — flake reproduction under real machine load.
# Runs K concurrent single-file vitest passes per round, R rounds, and records
# the actual failure text if capture-health.test.tsx flakes. Diagnosis only.

$root   = 'C:\Users\Ns8pc\Music\WARDRESS\frontend'
$scratch = 'C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch'
$log    = Join-Path $scratch 'audit4f_flake_load_results.txt'

Set-Location $root
function Record([string]$t) { Add-Content -Path $log -Value $t }

Record "=== load-flake probe start $(Get-Date -Format o) (K=5 concurrent, R=4 rounds) ==="

for ($round = 1; $round -le 4; $round++) {
    $jobs = @()
    for ($k = 1; $k -le 5; $k++) {
        $out = Join-Path $scratch ("audit4f_load_r{0}_k{1}.txt" -f $round, $k)
        $jobs += Start-Process -FilePath 'pnpm.cmd' `
            -ArgumentList 'exec','vitest','run','tests/capture-health.test.tsx' `
            -WorkingDirectory $root -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $out -RedirectStandardError ($out + '.err')
    }
    $jobs | Wait-Process
    for ($k = 1; $k -le 5; $k++) {
        $out = Join-Path $scratch ("audit4f_load_r{0}_k{1}.txt" -f $round, $k)
        $body = if (Test-Path $out) { Get-Content $out -Raw } else { '' }
        $verdict = if ($body -match 'failed') { 'FAIL' } elseif ($body -match 'passed') { 'PASS' } else { 'UNKNOWN' }
        Record ("round={0} k={1} verdict={2}" -f $round, $k, $verdict)
        if ($verdict -ne 'PASS') {
            Record '  ---- output ----'
            ($body -split "`n") | Where-Object { $_ -match 'FAIL|×|Unable to find|AssertionError|Tests |Test Files|Error' } | ForEach-Object { Record ("  " + $_.Trim()) }
        }
    }
}
Record "=== load-flake probe end $(Get-Date -Format o) ==="