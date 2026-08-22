"""Sandboxed end-to-end tests for scripts/uninstall.ps1's backup-completeness
contract (Phase 13).

Each test drives the REAL script (copied fresh from scripts/) inside a
temporary mini-repo against a fake `docker` shim whose behavior is forced per
scenario — no Docker engine or network involved. The properties under test:

- An attempted-but-incomplete backup STOPS the destructive teardown (exit 1,
  zero `compose down` / `volume rm` calls) unless -AllowIncompleteBackup is
  passed, in which case removal proceeds with honest reporting (exit 2).
- RESTORE.txt is generated from what this run actually captured, never a
  hardcoded manifest; a reused -BackupPath cannot leak artifacts from an
  earlier run into the current run's manifest.
- Deliberate -SkipBackup keeps its documented semantics (proceed, exit 0).

Requires `pwsh` (PowerShell 7+, present on developer machines and
GitHub-hosted runners). The script deletes <Desktop>/Wardress.lnk during
teardown, which resolves to the REAL user desktop even in the sandbox — a
module-scoped guard backs it up and restores it byte-identically.
"""

import hashlib
import os
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
        "pwsh (PowerShell 7+) is required for the uninstall backup-safety "
        "sandbox tests; it is preinstalled on developer machines and "
        "GitHub-hosted runners"
    )

SHIM_PS1 = r"""
$ErrorActionPreference = 'Continue'
$mode = if ($env:P13_MODE) { $env:P13_MODE } else { 'full_success' }
$log = $env:P13_LOG

function Write-Log([string]$Line) {
    if ($log) { Add-Content -Path $log -Value $Line -ErrorAction SilentlyContinue }
}

Write-Log ("CALL|" + ($args -join ' '))

$c0 = if ($args.Count -gt 0) { $args[0] } else { '' }
$c1 = if ($args.Count -gt 1) { $args[1] } else { '' }

if ($c0 -eq 'info') { exit 0 }

if ($c0 -eq 'volume') {
    Write-Log "VOLUME|$($args[1])|$($args[2])"
    exit 0
}

if ($c0 -eq 'rmi') { exit 0 }
if ($c0 -eq 'image') { exit 0 }

if ($c0 -eq 'run') {
    $dst = $null
    for ($i = 0; $i -lt $args.Count; $i++) {
        if ($args[$i] -eq '-v' -and $i + 1 -lt $args.Count) {
            $spec = $args[$i + 1]
            $idx = $spec.LastIndexOf(':')
            if ($idx -gt 0) {
                $hostPart = $spec.Substring(0, $idx)
                $contPart = $spec.Substring($idx + 1)
                if ($contPart -eq '/backup') { $dst = $hostPart }
            }
        }
    }
    if ($mode -eq 'tarfail') { exit 1 }
    if ($dst) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        $bytes = [byte[]](31,139,8,0,0,0,0,0,0,3,0,0,0,0,0,0,0,0)
        [IO.File]::WriteAllBytes((Join-Path $dst 'scan-artifacts.tar.gz'), $bytes)
    }
    exit 0
}

if ($c0 -eq 'compose') {
    switch ($c1) {
        'up' {
            if ($mode -eq 'wontstart') { exit 1 }
            exit 0
        }
        'exec' {
            $cmd = if ($args.Count -gt 4) { $args[4] } else { '' }
            if ($cmd -eq 'pg_isready') {
                if ($mode -eq 'neverready') { Start-Sleep -Milliseconds 100; exit 1 }
                exit 0
            }
            if ($cmd -eq 'pg_dump') {
                if ($mode -eq 'dumpfail') {
                    [Console]::Error.WriteLine('pg_dump: error: could not write to output file')
                    exit 1
                }
                Write-Output '-- PGDUMP stub'
                Write-Output "SET client_encoding = 'UTF8';"
                Write-Output 'CREATE TABLE stub (id int);'
                exit 0
            }
            exit 0
        }
        'config' {
            @{ services = @{ db = @{ image = 'postgres:16' } } } |
                ConvertTo-Json -Depth 5 -Compress | Write-Output
            exit 0
        }
        'down' {
            Write-Log 'TEARDOWN_DOWN'
            exit 0
        }
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
            assert restored == original_hash, (
                "Desktop shortcut failed to restore byte-identically after uninstall sandbox runs"
            )


@pytest.fixture()
def sandbox(tmp_path):
    mini = tmp_path / "mini"
    (mini / "scripts").mkdir(parents=True)
    for name in ("uninstall.ps1", "lib.ps1"):
        shutil.copy(REPO_ROOT / "scripts" / name, mini / "scripts" / name)
    (mini / ".env").write_text("POSTGRES_USER=wardress\nPOSTGRES_DB=wardress\n", encoding="ascii")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "shim.ps1").write_text(SHIM_PS1, encoding="ascii")
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

    def run(mode: str, tag: str, extra=(), timeout: float = 240):
        bdir = tmp_path / "backups" / tag
        log = tmp_path / f"invocations_{tag}.log"
        env = os.environ.copy()
        env["P13_MODE"] = mode
        env["P13_LOG"] = str(log)
        env["PATH"] = str(bin_dir) + os.path.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [
                PWSH,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(mini / "scripts" / "uninstall.ps1"),
                "-Force",
                "-BackupPath",
                str(bdir),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        output = proc.stdout + "\n" + (proc.stderr or "")
        restore_txt = bdir / "RESTORE.txt"
        return SimpleNamespace(
            returncode=proc.returncode,
            output=output,
            bdir=bdir,
            log=log,
            restore=(restore_txt.read_text(encoding="utf-8-sig") if restore_txt.exists() else None),
        )

    return SimpleNamespace(run=run, mini=mini)


def teardown_counts(log: Path) -> tuple[int, int]:
    if not log.exists():
        return 0, 0
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    down = sum(1 for line in lines if "TEARDOWN_DOWN" in line or " down " in line)
    volume_rm = sum(1 for line in lines if line.startswith("CALL|volume rm"))
    return down, volume_rm


def test_full_backup_completes_and_teardown_proceeds(sandbox):
    r = sandbox.run("full_success", "ok")
    assert r.returncode == 0
    assert "Backup completed successfully" in r.output
    down, volume_rm = teardown_counts(r.log)
    assert down >= 1 and volume_rm >= 4
    assert (r.bdir / "database.sql").exists()
    assert (r.bdir / "scan-artifacts.tar.gz").exists()
    assert "WARNING" not in r.restore
    for artifact in (".env", "database.sql", "scan-artifacts.tar.gz"):
        assert artifact in r.restore
    numbered = [
        line.strip()[:2]
        for line in r.restore.splitlines()
        if line.strip().startswith(("1.", "2.", "3.", "4.", "5."))
    ]
    assert numbered == ["1.", "2.", "3.", "4.", "5."]


def test_dump_failure_blocks_teardown_by_default(sandbox):
    r = sandbox.run("dumpfail", "dumpfail")
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "Backup completed successfully" not in r.output
    assert "INCOMPLETE" in r.output
    assert "Nothing was deleted" in r.output
    assert "database.sql (pg_dump failed)" in r.output
    assert r.restore is not None
    assert "WARNING: THIS BACKUP IS INCOMPLETE" in r.restore
    assert "- database.sql (pg_dump failed)" in r.restore
    contents_section = r.restore.split("To restore into a fresh install")[0]
    assert "database.sql            Logical" not in contents_section


def test_db_container_wontstart_blocks_teardown(sandbox):
    r = sandbox.run("wontstart", "wontstart")
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "database.sql (database container could not be started)" in r.output


def test_artifact_archive_failure_blocks_teardown(sandbox):
    r = sandbox.run("tarfail", "tarfail")
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "scan-artifacts.tar.gz (archive command failed)" in r.output
    contents_section = r.restore.split("To restore into a fresh install")[0]
    assert "scan-artifacts.tar.gz   Stored" not in contents_section


def test_db_never_ready_blocks_teardown(sandbox):
    r = sandbox.run("neverready", "neverready", timeout=300)
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "database.sql (database never became ready)" in r.output


def test_allow_incomplete_backup_proceeds_with_honest_reporting(sandbox):
    r = sandbox.run("dumpfail", "override", extra=("-AllowIncompleteBackup",))
    assert r.returncode == 2
    down, volume_rm = teardown_counts(r.log)
    assert down >= 1 and volume_rm >= 4
    assert "WARNING: the backup is INCOMPLETE:" in r.output
    assert "- database.sql (pg_dump failed)" in r.output
    assert r.restore is not None
    assert "WARNING: THIS BACKUP IS INCOMPLETE" in r.restore
    contents_section = r.restore.split("To restore into a fresh install")[0]
    assert "scan-artifacts.tar.gz   Stored" in contents_section
    assert "database.sql            Logical" not in contents_section


def test_skip_backup_keeps_documented_semantics(sandbox):
    r = sandbox.run("full_success", "skipbackup", extra=("-SkipBackup",))
    assert r.returncode == 0
    down, volume_rm = teardown_counts(r.log)
    assert down >= 1 and volume_rm >= 4
    assert "No backup was taken (-SkipBackup)." in r.output


def test_reused_backup_path_cannot_inherit_stale_artifacts(sandbox):
    bdir = sandbox.mini.parent / "backups" / "stale"
    bdir.mkdir(parents=True)
    (bdir / "database.sql").write_text("-- stale dump from an earlier run", encoding="ascii")
    (bdir / "scan-artifacts.tar.gz").write_bytes(bytes([0x1F, 0x8B, 0x08, 0, 0, 0, 0, 0, 0, 3]))
    r = sandbox.run("dumpfail", "stale")
    assert r.returncode == 1
    assert not (r.bdir / "database.sql").exists()
    contents_section = r.restore.split("To restore into a fresh install")[0]
    assert "database.sql            Logical" not in contents_section
    assert "- database.sql (pg_dump failed)" in r.restore


def test_missing_env_is_a_gap_not_a_failure(sandbox):
    (sandbox.mini / ".env").unlink()
    r = sandbox.run("full_success", "noenv")
    assert r.returncode == 0
    down, volume_rm = teardown_counts(r.log)
    assert down >= 1 and volume_rm >= 4
    contents_section = r.restore.split("To restore into a fresh install")[0]
    assert "Your configuration and secrets" not in contents_section
    assert "database.sql            Logical" in contents_section
