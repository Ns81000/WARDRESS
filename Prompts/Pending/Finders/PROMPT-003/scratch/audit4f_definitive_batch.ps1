# Audit Phase 4F — definitive Rule 18/5 batch (after scratch probes removed).
$root = 'C:\Users\Ns8pc\Music\WARDRESS\frontend'
$scratch = 'C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch'
$log = Join-Path $scratch 'audit4f_definitive_results.txt'
Set-Location $root
function Record([string]$t) { Add-Content -Path $log -Value $t }

Record "=== definitive batch start $(Get-Date -Format o) ==="

for ($i = 1; $i -le 3; $i++) {
    $json = Join-Path $scratch ("audit4f_def_repro_p{0}.json" -f $i)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & pnpm exec vitest run tests/phase4f-capture-surface-repros.test.tsx --reporter=json "--outputFile=$json" 2>&1 | Out-String
    $code = $LASTEXITCODE; $sw.Stop()
    $line = "REPRO pass {0}: exit={1} wall={2}s" -f $i, $code, [math]::Round($sw.Elapsed.TotalSeconds, 1)
    if (Test-Path $json) {
        $j = Get-Content $json -Raw | ConvertFrom-Json
        $line += " tests={0} failed={1} passed={2} success={3}" -f $j.numTotalTests, $j.numFailedTests, $j.numPassedTests, $j.success
        Record ("  durations: " + (($j.testResults.assertionResults | ForEach-Object { [math]::Round($_.duration) }) -join '/'))
    }
    Record $line
    if ($code -ne 0) { Record ("  STDOUT: " + $out) }
}

for ($i = 1; $i -le 3; $i++) {
    # plain run so the human-readable summary (and any Unhandled Errors
    # section) lands on stdout and can be recorded verbatim
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & pnpm exec vitest run 2>&1 | Out-String
    $code = $LASTEXITCODE; $sw.Stop()
    Record ("FULL pass {0}: exit={1} wall={2}s" -f $i, $code, [math]::Round($sw.Elapsed.TotalSeconds, 1))
    ($out -split "`n") | Where-Object { $_ -match 'Test Files|Tests |Duration|Unhandled|Error|failed|FAIL' } | ForEach-Object { Record ("  " + ($_.Trim() -replace "\x1b\[[0-9;]*m", "")) }
    if ($code -ne 0) {
        Record '  ---- full stdout ----'
        Record ($out -replace "\x1b\[[0-9;]*m", "")
    }
}

$lint = & pnpm lint 2>&1 | Out-String
Record ("LINT exit=" + $LASTEXITCODE + " : " + (($lint -split "`n") | Where-Object { $_ -match 'Found' }) -join ' ')
$tsc = & pnpm exec tsc -b 2>&1 | Out-String
Record ("TSC exit=" + $LASTEXITCODE + " output=[" + $tsc.Trim() + "]")
Record "=== definitive batch end $(Get-Date -Format o) ==="