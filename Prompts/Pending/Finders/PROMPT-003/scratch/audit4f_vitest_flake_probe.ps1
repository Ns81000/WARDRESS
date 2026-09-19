# Audit Phase 4F — capture-health.test.tsx flake characterization probe.
# Rule 18: many passes, per-test durations recorded; failures dumped in full.
# Diagnosis only: runs the existing suite, never edits production code.

$root   = 'C:\Users\Ns8pc\Music\WARDRESS\frontend'
$scratch = 'C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch'
$log    = Join-Path $scratch 'audit4f_flake_results.txt'

Set-Location $root
function Record([string]$text) { Add-Content -Path $log -Value $text }

Record "=== audit4f flake probe start $(Get-Date -Format o) ==="

function Invoke-Vitest {
    param([string]$jsonOut, [string[]]$targets)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & pnpm exec vitest run @targets --reporter=json "--outputFile=$jsonOut" 2>&1 | Out-String
    $sw.Stop()
    return @{ code = $LASTEXITCODE; elapsed = $sw.Elapsed.TotalSeconds; raw = $out }
}

function Summarize {
    param([string]$jsonPath)
    if (-not (Test-Path $jsonPath)) { return @('   (no json produced)') }
    try { $j = Get-Content $jsonPath -Raw | ConvertFrom-Json } catch { return @('   (json unparseable)') }
    $lines = @()
    foreach ($tr in $j.testResults) {
        foreach ($a in $tr.assertionResults) {
            $d = if ($a.duration) { [math]::Round($a.duration) } else { -1 }
            $lines += ("   {0,-7} {1,6}ms  {2}" -f $a.status, $d, $a.title)
        }
    }
    return $lines
}

# ---- Phase A: thin-load isolated runs of the flaky file -------------------
Record "--- Phase A: 15 isolated runs: tests/capture-health.test.tsx ---"
for ($i = 1; $i -le 15; $i++) {
    $json = Join-Path $scratch ("audit4f_a{0}.json" -f $i)
    $r = Invoke-Vitest -jsonOut $json -targets @('tests/capture-health.test.tsx')
    Record ("A{0,2}: exit={1} wall={2}s" -f $i, $r.code, [math]::Round($r.elapsed, 1))
    Summarize -jsonPath $json | ForEach-Object { Record $_ }
    if ($r.code -ne 0) { Record '   ---- raw output ----'; Record $r.raw }
}
Record "--- Phase A complete $(Get-Date -Format o) ---"

# ---- Phase B: full-suite runs (the historical flake precondition) ---------
Record "--- Phase B: full suite x3 (pnpm test) ---"
for ($i = 1; $i -le 3; $i++) {
    $json = Join-Path $scratch ("audit4f_b{0}.json" -f $i)
    $r = Invoke-Vitest -jsonOut $json -targets @()
    Record ("B{0}: exit={1} wall={2}s" -f $i, $r.code, [math]::Round($r.elapsed, 1))
    # only the capture-health file's tests plus any failure block
    if (Test-Path $json) {
        try {
            $j = Get-Content $json -Raw | ConvertFrom-Json
            foreach ($tr in $j.testResults) {
                if ($tr.name -like '*capture-health*') {
                    foreach ($a in $tr.assertionResults) {
                        Record ("   {0,-7} {1,6}ms  {2}" -f $a.status, [math]::Round($a.duration), $a.title)
                    }
                }
            }
            Record ("   totals: {0} tests, {1} failed, {2} passed" -f $j.numTotalTests, $j.numFailedTests, $j.numPassedTests)
        } catch { Record '   (json unparseable)' }
    }
    if ($r.code -ne 0) {
        Record '   ---- failing assertions (all files) ----'
        if (Test-Path $json) {
            try {
                $j = Get-Content $json -Raw | ConvertFrom-Json
                foreach ($tr in $j.testResults) {
                    foreach ($a in $tr.assertionResults) {
                        if ($a.status -eq 'failed') {
                            Record ("   FAILED {0} :: {1}" -f $tr.name, $a.title)
                            foreach ($m in $a.failureMessages) { Record ("     " + ($m -replace "`r?`n", " | ").Substring(0, [Math]::Min(600, $m.Length))) }
                        }
                    }
                }
            } catch { Record '   (json unparseable)' }
        }
    }
}
Record "=== audit4f flake probe end $(Get-Date -Format o) ==="