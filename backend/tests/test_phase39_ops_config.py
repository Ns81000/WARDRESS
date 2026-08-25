"""Phase 39 — ops/scripts & config sweep tests.

Five findings, one sandbox methodology for the script halves (mirroring
Phase 29/13's fake-docker harness; every script test drives the REAL
scripts copied fresh from scripts/):

Finding "Failed image builds leave build log litter in the repo root":
    Build logs land in a dedicated .build-logs directory (never the repo
    root), are removed again on success, and the failure hint names the
    .err.log file that actually carries the error output.

Finding "Installer/updater console-output integrity":
    The displayed step budget matches the steps that actually execute on
    every path (no [12/11 - 109%] overflows, no stalling below 100%), no
    stray "True" lines leak from uncaptured Build-Service returns, and the
    TypeScript pre-flight step closes with its own label.

Finding "diagnostics.ps1 writes its bundle into the repo root":
    The bundle defaults outside the repository and every line is scrubbed
    of the deployment's own configured secrets plus common token shapes
    before it is written, so the "share this file" instruction is safe.

Finding "Six Settings fields are env-overridable in code but forwarded by
neither compose nor .env.example":
    Five deployable fields are forwarded by compose and documented in
    .env.example (with an env-name -> pydantic-field binding test);
    ARTIFACTS_DIR is deliberately documented as compose-pinned instead of
    forwarded (the volume mounts pin /data/artifacts in both containers);
    the dead WARDRESS_ENV knob is gone.

Finding "Successful catalog syncs rewrite a tracked source-tree file at
runtime":
    A successful live catalog sync updates ONLY the database; the bundled
    snapshot file stays byte-identical, and the write-back helper is gone.

Requires `pwsh` (PowerShell 7+), mirroring Phase 29.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PWSH = shutil.which("pwsh")
if PWSH is None:
    raise RuntimeError(
        "pwsh (PowerShell 7+) is required for the Phase 39 ops-scripts "
        "sandbox tests; it is preinstalled on developer machines and "
        "GitHub-hosted runners"
    )

SHIM_PS1 = r"""
$ErrorActionPreference = 'Continue'
$mode = if ($env:P39_MODE) { $env:P39_MODE } else { 'ok' }
$log = $env:P29_LOG

function Write-ShimLog([string]$Line) {
    if ($log) { Add-Content -Path $log -Value $Line -ErrorAction SilentlyContinue }
}

$c0 = if ($args.Count -gt 0) { $args[0] } else { '' }
$c1 = if ($args.Count -gt 1) { $args[1] } else { '' }

Write-ShimLog ("CALL|" + ($args -join ' '))

if ($c0 -eq 'info') {
    if ($mode -eq 'enginedown') { exit 1 }
    exit 0
}
if ($c0 -eq '--version' -or $c0 -eq 'volume' -or $c0 -eq 'rmi' -or $c0 -eq 'image') {
    exit 0
}
if ($c0 -eq 'run') {
    # docker run --rm -v ... (uninstall artifact tar helper): produce a tar.
    $dst = $null
    for ($i = 0; $i -lt $args.Count; $i++) {
        if ($args[$i] -eq '-v' -and $i + 1 -lt $args.Count) {
            $spec = $args[$i + 1]; $idx = $spec.LastIndexOf(':')
            $contPart = if ($idx -gt 0) { $spec.Substring($idx + 1) } else { '' }
            if ($contPart -eq '/backup') { $dst = $spec.Substring(0, $idx) }
        }
    }
    if ($dst) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        $tarBytes = [byte[]](31,139,8,0,0,0,0,0,0,3)
        [IO.File]::WriteAllBytes((Join-Path $dst 'scan-artifacts.tar.gz'), $tarBytes)
    }
    exit 0
}
if ($c0 -eq 'compose') {
    $joined = $args -join ' '
    # Profile-prefixed compose commands put --profile at position 1, so the
    # switch below (keyed on $c1) never sees their verb; match on the joined
    # arguments instead.
    if ($joined -match '\bps\b.*telegram-bot') {
        if ($env:P39_BOT_RUNNING -eq '1') { Write-Output 'abc123' }
        exit 0
    }
    if ($mode -eq 'botfail' -and $joined -match '--force-recreate telegram-bot') {
        exit 1
    }
    switch ($c1) {
        'build' {
            if ($mode -eq 'buildfail') {
                [Console]::Error.WriteLine('ERROR: failed to solve: app: copy /app/dist: not found')
                exit 1
            }
            exit 0
        }
        'up' {
            if ($mode -eq 'wontstart') { exit 1 }
            if ($mode -eq 'beatfail' -and $args[$args.Count - 1] -eq 'beat') { exit 1 }
            if ($mode -eq 'botfail' -and $args[$args.Count - 1] -eq 'telegram-bot') { exit 1 }
            exit 0
        }
        'run' {
            if ($mode -eq 'migfail' -and $joined -match 'alembic') { exit 1 }
            exit 0
        }
        'exec' {
            if ($joined -match 'pg_isready') { exit 0 }
            if ($joined -match 'pg_dump') {
                $fakeRoot = $env:P29_CONTAINER_DIR
                New-Item -ItemType Directory -Force -Path $fakeRoot | Out-Null
                [IO.File]::WriteAllText(
                    (Join-Path $fakeRoot 'wardress-uninstall-dump.sql'),
                    "-- header`nINSERT INTO stub VALUES (1);`n")
                exit 0
            }
            if ($joined -match ' rm ') { exit 0 }
            exit 0
        }
        'cp' {
            $dst = if ($args.Count -gt 3) { $args[3] } else { '' }
            $fakeDump = Join-Path $env:P29_CONTAINER_DIR 'wardress-uninstall-dump.sql'
            if ((Test-Path $fakeDump) -and $dst) { Copy-Item $fakeDump $dst -Force }
            exit 0
        }
        'config' {
            @{ services = @{ db = @{ image = 'postgres:16' } } } |
                ConvertTo-Json -Depth 5 -Compress | Write-Output
            exit 0
        }
        'ps' {
            if ($env:P39_BOT_RUNNING -eq '1') { Write-Output 'abc123' }
            exit 0
        }
        'logs' {
            Write-Output 'app-1  | listening on 8000'
            Write-Output 'app-1  | loaded config jwt=hunter2-secret-value'
            Write-Output 'worker-1 | upstream key sk-live-abcdef1234567890'
            exit 0
        }
        'down' { Write-ShimLog 'TEARDOWN_DOWN'; exit 0 }
        default { exit 0 }
    }
}
exit 0
"""


def _desktop_lnk() -> Path | None:
    try:
        out = subprocess.run(
            [PWSH, "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    candidate = Path(out.stdout.strip()) if out.returncode == 0 else None
    if candidate and (candidate / "Wardress.lnk").exists():
        return candidate / "Wardress.lnk"
    return None


@pytest.fixture(scope="module")
def desktop_shortcut_guard():
    """uninstall.ps1 deletes <Desktop>/Wardress.lnk during teardown, which
    resolves to the REAL user desktop even in the sandbox; back it up and
    restore it byte-identically."""
    lnk = _desktop_lnk()
    if lnk is None:
        yield None
        return
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        backup = Path(td) / "Wardress.lnk"
        shutil.copy2(lnk, backup)
        original_hash = hashlib.sha256(lnk.read_bytes()).hexdigest()
        try:
            yield lnk
        finally:
            shutil.copy2(backup, lnk)
            restored = hashlib.sha256(lnk.read_bytes()).hexdigest()
            assert restored == original_hash


@pytest.fixture()
def sandbox(tmp_path):
    mini = tmp_path / "mini"
    (mini / "scripts").mkdir(parents=True)
    for name in (
        "uninstall.ps1",
        "install.ps1",
        "update.ps1",
        "validate.ps1",
        "diagnostics.ps1",
        "lib.ps1",
    ):
        shutil.copy(REPO_ROOT / "scripts" / name, mini / "scripts" / name)
    # JWT_SECRET doubles as the diagnostics-redaction probe value.
    (mini / ".env").write_text(
        "POSTGRES_USER=wardress\nPOSTGRES_DB=wardress\nJWT_SECRET=hunter2-secret-value\n",
        encoding="ascii",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "shim.ps1").write_text(SHIM_PS1, encoding="utf-8")
    if sys.platform == "win32":
        (bin_dir / "docker.cmd").write_text(
            '@echo off\r\npwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0shim.ps1" %*\r\n',
            encoding="ascii",
        )
    else:
        launcher = bin_dir / "docker"
        launcher.write_text(
            '#!/bin/sh\nexec pwsh -NoProfile -File "$(dirname "$0")/shim.ps1" "$@"\n',
            encoding="ascii",
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def run(
        script: str,
        mode: str,
        tag: str,
        extra=(),
        timeout: float = 240,
        env_extra: dict | None = None,
        with_backup_path: bool = False,
    ):
        bdir = tmp_path / "backups" / tag
        log = tmp_path / f"invocations_{tag}.log"
        env = os.environ.copy()
        env["P39_MODE"] = mode
        env["P29_MODE"] = mode
        env["P29_LOG"] = str(log)
        env["P29_CONTAINER_DIR"] = str(tmp_path / f"fakecontainer_{tag}")
        os.makedirs(env["P29_CONTAINER_DIR"], exist_ok=True)
        env["PATH"] = str(bin_dir) + os.path.pathsep + env.get("PATH", "")
        if env_extra:
            env.update(env_extra)

        argv = [
            PWSH,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(mini / "scripts" / script),
        ]
        if with_backup_path:
            argv += ["-Force", "-BackupPath", str(bdir)]
        argv += list(extra)

        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        output = proc.stdout + "\n" + (proc.stderr or "")
        return SimpleNamespace(
            returncode=proc.returncode,
            output=output,
            log=log,
            bdir=bdir,
            mini=mini,
        )

    return SimpleNamespace(run=run, mini=mini, tmp_path=tmp_path)


def _step_headers(output: str) -> list[str]:
    return [
        line.strip().split()[0]
        for line in output.splitlines()
        if line.strip().startswith("[") and "/-" not in line and "] ==>" in line
    ]


# ---------------------------------------------------------------------------
# Finding: Failed image builds leave build log litter in the repo root
# ---------------------------------------------------------------------------


def test_failed_build_keeps_logs_out_of_the_repo_root(sandbox):
    """A failed image build must leave its logs in .build-logs/ (never the
    repo root) and the failure hint must point at the .err.log file that
    actually carries the error output."""
    r = sandbox.run("update.ps1", "buildfail", "buildfail")
    assert r.returncode != 0
    err_log = r.mini / ".build-logs" / "build_app.err.log"
    stdout_log = r.mini / ".build-logs" / "build_app.log"
    assert err_log.exists(), "build error log missing from .build-logs"
    assert "failed to solve" in err_log.read_text(encoding="utf-8", errors="replace")
    assert stdout_log.exists(), "build stdout log missing from .build-logs"
    # THE filed defect: root-level litter.
    assert not (r.mini / "build_app.err.log").exists(), "build log litter left in the repo root"
    assert not (r.mini / "build_app.log").exists()
    # Hint names the file with the actionable content, with its location.
    assert "build_app.err.log" in r.output
    assert ".build-logs" in r.output


def test_build_service_log_directory_contract_both_branches(sandbox, tmp_path):
    """Direct contract of lib.ps1's Build-Service against the fake-docker
    shim: the SUCCESS branch removes both log files and the empty directory;
    the FAILURE branch keeps them for diagnosis and exits nonzero."""
    bin_dir = tmp_path / "driverbin"
    bin_dir.mkdir()
    (bin_dir / "shim.ps1").write_text(SHIM_PS1, encoding="utf-8")
    if sys.platform == "win32":
        (bin_dir / "docker.cmd").write_text(
            '@echo off\r\npwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0shim.ps1" %*\r\n',
            encoding="ascii",
        )
    else:
        launcher = bin_dir / "docker"
        launcher.write_text(
            '#!/bin/sh\nexec pwsh -NoProfile -File "$(dirname "$0")/shim.ps1" "$@"\n',
            encoding="ascii",
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    driver = tmp_path / "driver.ps1"
    driver.write_text(
        "param([string]$LibPath, [string]$LogDir)\n"
        ". $LibPath\n"
        "$null = Build-Service @() 'app' 'unused hint' $LogDir\n"
        "Write-Output ('DIR_EXISTS=' + (Test-Path $LogDir))\n",
        encoding="utf-8",
    )

    def drive(mode: str, tag: str):
        env = os.environ.copy()
        env["P39_MODE"] = mode
        env["P29_MODE"] = mode
        env["P29_LOG"] = str(tmp_path / f"driver_{tag}.log")
        env["P29_CONTAINER_DIR"] = str(tmp_path / f"drivercontainer_{tag}")
        os.makedirs(env["P29_CONTAINER_DIR"], exist_ok=True)
        env["PATH"] = str(bin_dir) + os.path.pathsep + env.get("PATH", "")
        log_dir = tmp_path / f"logs_{tag}"
        return subprocess.run(
            [
                PWSH,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(driver),
                "-LibPath",
                str(REPO_ROOT / "scripts" / "lib.ps1"),
                "-LogDir",
                str(log_dir),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180,
        ), log_dir

    # Success: builds clean, logs gone, empty dir removed.
    proc, log_dir = drive("ok", "success")
    combined = proc.stdout + "\n" + (proc.stderr or "")
    assert proc.returncode == 0, combined
    assert "Built app successfully" in combined
    assert not (log_dir / "build_app.err.log").exists()
    assert not (log_dir / "build_app.log").exists()
    assert "DIR_EXISTS=False" in combined, "empty log dir was not cleaned up"

    # Failure: logs retained in the dedicated directory, exit nonzero.
    proc, log_dir = drive("buildfail", "failure")
    combined = proc.stdout + "\n" + (proc.stderr or "")
    assert proc.returncode != 0
    assert (log_dir / "build_app.err.log").exists()
    assert (log_dir / "build_app.log").exists()
    assert "failed to solve" in (log_dir / "build_app.err.log").read_text(
        encoding="utf-8", errors="replace"
    )


def test_gitignore_covers_build_logs_and_diagnostics_bundles():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".build-logs/" in text
    assert "diagnostics_*.txt" in text
    assert "build_*.log" in text and "build_*.err.log" in text


# ---------------------------------------------------------------------------
# Finding: Installer/updater console-output integrity
# ---------------------------------------------------------------------------


def test_update_step_budget_matches_executed_steps(sandbox):
    """The declared budget must equal the steps that will actually run: a
    normal update (no source pull possible in the sandbox, no bot running)
    declares 12 steps, so the late failing step prints [11/12] — and no
    header anywhere overflows its denominator (pre-fix the same run printed
    [n/11] headers and overflowed to '[12/11 - 109%]' at step 12)."""
    r = sandbox.run("update.ps1", "beatfail", "budget_plain")
    assert r.returncode != 0
    assert "[11/12 - 92%]" in r.output, r.output
    for line in r.output.splitlines():
        line = line.strip()
        if "%]" in line and line.startswith("["):
            m = re.match(r"\[(\d+)/(\d+) - (\d+)%\]", line)
            if m:
                assert int(m.group(1)) <= int(m.group(2)), f"progress overflow: {line}"


def test_update_budget_counts_conditional_bot_recreate(sandbox):
    """When the optional telegram-bot is detected running, one extra step is
    budgeted (13) instead of overflowing past a stale total: the injected
    failure at the bot-recreate step prints [12/13 - 92%] where pre-fix the
    same shape printed the literal overflow '[12/11 - 109%]'."""
    r = sandbox.run("update.ps1", "botfail", "budget_bot", env_extra={"P39_BOT_RUNNING": "1"})
    assert r.returncode != 0
    assert "[12/13 - 92%]" in r.output, r.output
    assert "109%" not in r.output


def test_no_stray_true_lines_after_build_steps(sandbox):
    """Build-Service's boolean return must be consumed: no bare 'True' line
    may follow the build steps in any transcript."""
    r = sandbox.run("update.ps1", "beatfail", "no_true")
    assert r.returncode != 0
    stray = [ln for ln in r.output.splitlines() if ln.strip() == "True"]
    assert stray == [], f"stray 'True' transcript lines leaked: {stray}"


def test_typescript_preflight_step_closes_with_its_own_label(sandbox):
    """install.ps1's TypeScript step must close with a truthful label, and
    'Docker engine is running' must appear exactly once (step 1's completion),
    not again as the TypeScript step's closing line."""
    r = sandbox.run("install.ps1", "migfail", "install_label")
    assert r.returncode != 0
    assert "Pre-flight TypeScript validation complete" in r.output
    assert r.output.count("Docker engine is running") == 1, r.output


def test_uninstall_reaches_exactly_100_percent_on_every_path(sandbox, desktop_shortcut_guard):
    """Per-path budgets: standard backup run ends [7/7 - 100%], -SkipBackup
    [3/3 - 100%], and -PruneBaseImages adds its step to both (8/8 and 4/4).
    Pre-fix these stalled at [7/8 - 88%] and [3/4 - 75%]."""
    r = sandbox.run("uninstall.ps1", "ok", "pct_full", with_backup_path=True)
    assert r.returncode == 0, r.output
    assert "[7/7 - 100%]" in r.output, r.output

    r = sandbox.run("uninstall.ps1", "ok", "pct_skip", extra=("-Force", "-SkipBackup"))
    assert r.returncode == 0, r.output
    assert "[3/3 - 100%]" in r.output, r.output

    r = sandbox.run(
        "uninstall.ps1",
        "ok",
        "pct_prune",
        extra=("-PruneBaseImages",),
        with_backup_path=True,
    )
    assert r.returncode == 0, r.output
    assert "[8/8 - 100%]" in r.output, r.output

    r = sandbox.run(
        "uninstall.ps1",
        "ok",
        "pct_skip_prune",
        extra=("-Force", "-SkipBackup", "-PruneBaseImages"),
    )
    assert r.returncode == 0, r.output
    assert "[4/4 - 100%]" in r.output, r.output


# ---------------------------------------------------------------------------
# Finding: diagnostics.ps1 writes its bundle into the repo root
# ---------------------------------------------------------------------------


def test_diagnostics_bundle_scrubs_secrets_before_sharing(sandbox, tmp_path):
    """Every line of the shareable bundle is scrubbed: the deployment's own
    configured secrets (parsed from .env) and common token shapes never
    reach disk, while ordinary log text survives."""
    out_path = tmp_path / "diag_bundle.txt"
    r = sandbox.run(
        "diagnostics.ps1",
        "ok",
        "diag_redact",
        extra=("-OutputPath", str(out_path)),
    )
    assert r.returncode == 0, r.output
    bundle = out_path.read_text(encoding="utf-8-sig")
    assert "hunter2-secret-value" not in bundle, "configured JWT_SECRET leaked"
    assert "sk-live-abcdef1234567890" not in bundle, "token-shaped secret leaked"
    assert "<redacted>" in bundle, "scrubber did not fire at all"
    assert "listening on 8000" in bundle, "ordinary log text was lost"


def test_diagnostics_default_output_lands_outside_the_repository():
    """Source pin: the default OutputPath derives from the user's Documents
    folder (falling back to TEMP) and never from the repo root."""
    src = (REPO_ROOT / "scripts" / "diagnostics.ps1").read_text(encoding="utf-8")
    default_branch = src.split("if (-not $OutputPath)")[1].split("}")[0]
    assert "MyDocuments" in default_branch
    assert "TEMP" in default_branch
    assert "$RepoRoot" not in default_branch


# ---------------------------------------------------------------------------
# Finding: Six Settings fields forwarded by neither compose nor .env.example
# ---------------------------------------------------------------------------

FORWARDED_FIELDS = [
    ("ACCESS_TOKEN_TTL", "access_token_ttl"),
    ("REFRESH_TOKEN_TTL", "refresh_token_ttl"),
    ("MAX_SESSION_TTL", "max_session_ttl"),
    ("JWT_LEEWAY_SECONDS", "jwt_leeway_seconds"),
    ("MAX_REQUEST_BODY_BYTES", "max_request_body_bytes"),
]


def _compose_service_block(service: str) -> str:
    lines = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"  {service}:"):
            block = []
            for following in lines[i + 1 :]:
                if following.startswith("  ") and not following.startswith("   "):
                    break  # next top-level service key at two-space indent
                block.append(following)
            return "\n".join(block)
    raise AssertionError(f"could not locate the {service} service block")


@pytest.mark.parametrize("env_name,_field", FORWARDED_FIELDS)
def test_compose_forwards_tunable_settings_to_the_app_service(env_name, _field):
    """Each tunable Settings field must be forwarded into the app container
    (before the fix they were silent no-ops: compose drops unlisted vars)."""
    app_block = _compose_service_block("app")
    assert f"{env_name}:" in app_block, f"{env_name} not forwarded to the app service"


@pytest.mark.parametrize("env_name,_field", FORWARDED_FIELDS)
def test_env_example_documents_the_tunable_settings(env_name, _field):
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"{env_name}=" in example, f"{env_name} undocumented in .env.example"


def test_env_names_bind_to_pydantic_fields(monkeypatch):
    """THE forwarding-contract proof: each compose/.env name maps onto the
    pydantic field it claims to configure (a typo'd forward would silently
    no-op again)."""
    overrides = {
        "ACCESS_TOKEN_TTL": "111",
        "REFRESH_TOKEN_TTL": "222",
        "MAX_SESSION_TTL": "333",
        "JWT_LEEWAY_SECONDS": "44",
        "MAX_REQUEST_BODY_BYTES": "555",
    }
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    from app.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        jwt_secret="x" * 40,
        credentials_encryption_key="y" * 40,
    )
    assert settings.access_token_ttl == 111
    assert settings.refresh_token_ttl == 222
    assert settings.max_session_ttl == 333
    assert settings.jwt_leeway_seconds == 44
    assert settings.max_request_body_bytes == 555


def test_artifacts_dir_documented_as_compose_pinned_not_forwarded():
    """ARTIFACTS_DIR is deliberately NOT forwarded: the compose volume mounts
    pin /data/artifacts inside both containers, so forwarding it would trade
    one silent no-op for a worse silent misconfiguration trap. It must be
    documented as such instead."""
    app_block = _compose_service_block("app")
    worker_block = _compose_service_block("worker")
    assert "ARTIFACTS_DIR:" not in app_block
    assert "ARTIFACTS_DIR:" not in worker_block
    assert "/data/artifacts" in app_block and "/data/artifacts" in worker_block
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ARTIFACTS_DIR" in example, "the deliberate non-forwarding decision must be documented"


def test_dead_wardress_env_knob_removed_from_env_example():
    """WARDRESS_ENV was read by nothing anywhere in the repo; presenting it
    as configuration eroded trust in the rest of the file."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "WARDRESS_ENV" not in example
    compose_text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "WARDRESS_ENV" not in compose_text


# ---------------------------------------------------------------------------
# Finding: Successful catalog syncs rewrite a tracked source-tree file
# ---------------------------------------------------------------------------


async def test_live_catalog_sync_never_rewrites_the_bundled_snapshot(db_factory, monkeypatch):
    """A successful live fetch must update ONLY the database: the tracked
    snapshot file stays byte-identical (pre-fix, startup rewrote it with a
    fresh generated_at, leaving checkout-based installs permanently dirty)."""
    from app import ai_catalog

    snapshot_path = ai_catalog._SNAPSHOT_PATH
    original_bytes = snapshot_path.read_bytes()

    tiny = {
        "providers": [
            {
                "id": "openai",
                "name": "OpenAI",
                "env": [],
                "api_base": None,
                "doc": None,
                "npm": None,
            }
        ],
        "models": [
            {
                "id": "openai/gpt-x",
                "provider_id": "openai",
                "model_id": "gpt-x",
                "display_name": "GPT-X",
                "context_window": 1,
                "max_output_tokens": 1,
                "tool_calling": False,
                "reasoning": False,
                "cost_input": None,
                "cost_output": None,
            }
        ],
    }

    async def live(*a, **k):
        return dict(tiny)

    monkeypatch.setattr(ai_catalog, "fetch_live_catalog", live)
    try:
        async with db_factory() as db:
            result = await ai_catalog.sync_catalog(db)
        assert result["source"] == "live"
        assert result["models"] == 1
        assert snapshot_path.read_bytes() == original_bytes, (
            "bundled snapshot file was rewritten at runtime"
        )
    finally:
        # Safety net: never leave the tree dirty even if an assertion above
        # fails against a regressed tree.
        if snapshot_path.read_bytes() != original_bytes:
            snapshot_path.write_bytes(original_bytes)


def test_snapshot_writeback_helper_is_gone_and_seed_intact():
    """Structural pins for the removal: no runtime writer of the bundled
    file exists anywhere in the module, the docstring no longer claims the
    opportunistic refresh, and the static seed still loads."""
    from app import ai_catalog

    assert not hasattr(ai_catalog, "_write_snapshot"), (
        "_write_snapshot must not exist: runtime code must never rewrite the "
        "tracked source-tree snapshot"
    )
    src = (REPO_ROOT / "backend" / "app" / "ai_catalog.py").read_text(encoding="utf-8")
    assert "_write_snapshot" not in src
    assert "opportunistically rewrites" not in src
    snap = ai_catalog.load_snapshot()
    assert snap is not None, "bundled offline seed must still ship and load"
    assert len(snap["models"]) > 100
