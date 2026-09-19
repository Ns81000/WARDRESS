# Audit Phase 4F — Rule 18 repeatability + Rule 5 regression batch.
$root = 'C:\Users\Ns8pc\Music\WARDRESS\frontend'
$scratch = 'C:\Users\Ns8pc\Music\WARDRESS\Prompts\Pending\Finders\PROMPT-003\scratch'
$log = Join-Path $scratch 'audit4f_final_results.txt'
Set-Location $root
function Record([string]$t) { Add-Content -Path $log -Value $t }

Record "=== audit4f final batch start $(Get-Date -Format o) ==="

# 1. Rule 18: three passes of the new repro file
for ($i = 1; $i -le 3; $i++) {
    $json = Join-Path $scratch ("audit4f_repro_p{0}.json" -f $i)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & pnpm exec vitest run tests/phase4f-capture-surface-repros.test.tsx --reporter=json "--outputFile=$json" 2>&1 | Out-String
    $code = $LASTEXITCODE
    $sw.Stop()
    $line = "REPRO pass {0}: exit={1} wall={2}s" -f $i, $code, [math]::Round($sw.Elapsed.TotalSeconds, 1)
    if (Test-Path $json) {
        try {
            $j = Get-Content $json -Raw | ConvertFrom-Json
            $line += " tests={0} failed={1} passed={2}" -f $j.numTotalTests, $j.numFailedTests, $j.numPassedTests
            $durs = ($j.testResults.assertionResults | ForEach-Object { [math]::Round($_.duration) }) -join '/'
            Record ("  durations: " + $durs)
        } catch { $line += " (json unparseable)" }
    }
    Record $line
    if ($code -ne 0) { Record '  RAW:'; Record $out }
}

# 2. Rule 5: full suite regression (three passes, whole gate)
for ($i = 1; $i -le 3; $i++) {
    $json = Join-Path $scratch ("audit4f_full_p{0}.json" -f $i)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = & pnpm exec vitest run --reporter=json "--outputFile=$json" 2>&1 | Out-String
    $code = $LASTEXITCODE
    $sw.Stop()
    $line = "FULL pass {0}: exit={1} wall={2}s" -f $i, $code, [math]::Round($sw.Elapsed.TotalSeconds, 1)
    if (Test-Path $json) {
        try {
            $j = Get-Content $json -Raw | ConvertFrom-Json
            $line += " files={0} tests={1} failed={2} passed={3}" -f $j.numTotalTestSuites, $j.numTotalTests, $j.numFailedTests, $j.numPassedTests
            foreach ($tr in $j.testResults) {
                foreach ($a in $tr.assertionResults) {
                    if ($a.status -ne 'passed') {
                        Record ("  NOT-PASSED {0} :: {1} :: {2}" -f $a.status, $tr.name, $a.title)
                        foreach ($m in $a.failureMessages) { Record ("    " + ($m -replace "`r?`n", " | ")) }
                    }
                    if ($tr.name -like '*capture-health*') {
                        Record ("  capture-health {0,7}ms {1}" -f [math]::Round($a.duration), $a.title)
                    }
                }
            }
        } catch { $line += " (json unparseable)" }
    }
    Record $line
    if ($code -ne 0) { Record '  RAW tail:'; Record ($out.Substring([Math]::Max(0, $out.Length - 2000))) }
}

# 3. Gates
$lint = & pnpm lint 2>&1 | Out-String
Record ("LINT exit=" + $LASTEXITCODE)
Record ("  " + (($lint -split "`n") | Where-Object { $_ -match 'Found|error' } | Select-Object -Last 3) -join ' ')
$tsc = & pnpm exec tsc -b 2>&1 | Out-String
Record ("TSC exit=" + $LASTEXITCODE + " output=" + $tsc.Trim())
Record "=== audit4f final batch end $(Get-Date -Format o) ==="