"""Phase 29 — ops/scripts robustness tests.

Three findings, one sandbox methodology (mirroring Phase 13's fake-docker
harness; every script test drives the REAL scripts copied fresh from
scripts/):

Finding "Database backup/restore silently destroys all non-ASCII content":
    The uninstaller must capture database.sql byte-exactly regardless of
    host shell. The dump is produced INSIDE the container and copied out
    with `docker compose cp`, so no PowerShell text layer ever re-encodes
    it; the RESTORE.txt recipe loads via psql -f inside the container.
    Verified byte-for-byte under both pwsh 7 and Windows PowerShell 5.1
    against a shim whose pg_dump emits raw UTF-8 bytes containing Arabic,
    Japanese, an em-dash, and an accented Latin character.

Finding "Every entry-point script hangs forever when the Docker CLI wedges":
    A wedged Docker CLI must produce a bounded, readable failure instead of
    an indefinite silent hang. Invoke-NativeWithDeadline returns $null on
    deadline and every entry-point preflight translates that into its own
    actionable message.

Finding "ADMIN_RESET_PASSWORD emergency-recovery knob is unreachable":
    Compose forwards the flag into the app container, .env.example
    documents it, and seed_admin prints a recovery procedure whose command
    actually works.

Requires `pwsh` (PowerShell 7+). The Windows PowerShell 5.1 byte-exactness
test additionally requires `powershell` and states its skip reason on
platforms where it does not exist (the property itself is verified
everywhere under pwsh, which shares the fix's mechanism).
"""

import base64
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PWSH = shutil.which("pwsh")
if PWSH is None:
    raise RuntimeError(
        "pwsh (PowerShell 7+) is required for the Phase 29 ops-scripts "
        "sandbox tests; it is preinstalled on developer machines and "
        "GitHub-hosted runners"
    )

PS51 = shutil.which("powershell")

# Raw UTF-8 payload the shim's pg_dump writes: ASCII SQL framing around
# non-ASCII content that every broken encoding path mangles differently.
ARABIC = "\u0627\u062e\u062a\u0631\u0627\u0642"
JAPANESE = "\u65e5\u672c\u8a9e"
EMDASH = "\u2014"
EACUTE = "\u00e9"
EXPECTED_DUMP = (
    "--\n-- PostgreSQL database dump\n"
    "SET client_encoding = 'UTF8';\n"
    f"INSERT INTO stub (note) VALUES ('HACKED BY TEST - arabic: {ARABIC} "
    f"japanese: {JAPANESE} em-dash: {EMDASH} accented: {EACUTE}');\n-- end\n"
).encode()


SHIM_PS1 = r"""
$ErrorActionPreference = 'Continue'
$mode = if ($env:P29_MODE) { $env:P29_MODE } else { 'ok' }
$log = $env:P29_LOG

function Write-ShimLog([string]$Line) {
    if ($log) { Add-Content -Path $log -Value $Line -ErrorAction SilentlyContinue }
}

$c0 = if ($args.Count -gt 0) { $args[0] } else { '' }
$c1 = if ($args.Count -gt 1) { $args[1] } else { '' }

Write-ShimLog ("CALL|" + ($args -join ' '))

# Fake container filesystem: since Phase 29 the script dumps INSIDE the
# container (sh -c "... > /tmp/...") and copies out with `compose cp`.
$fakeRoot = $env:P29_CONTAINER_DIR
New-Item -ItemType Directory -Force -Path $fakeRoot | Out-Null
$fakeDump = Join-Path $fakeRoot 'wardress-uninstall-dump.sql'

if ($c0 -eq 'info') {
    if ($mode -eq 'enginedown') { exit 1 }
    if ($mode -eq 'hang_info') {
        # Hang only the FIRST info probe so multi-probe entry points still
        # terminate inside the watchdog after their bounded failure.
        $countFile = Join-Path $fakeRoot 'info_calls'
        $n = 0
        if (Test-Path $countFile) { $n = [int](Get-Content $countFile) }
        Set-Content -Path $countFile -Value ($n + 1)
        if ($n -eq 0) { Start-Sleep -Seconds 600 }
    }
    exit 0
}
if ($c0 -eq '--version' -or $c0 -eq 'volume' -or $c0 -eq 'rmi' -or $c0 -eq 'image') {
    exit 0
}
if ($c0 -eq 'run') {
    $dst = $null
    for ($i = 0; $i -lt $args.Count; $i++) {
        if ($args[$i] -eq '-v' -and $i + 1 -lt $args.Count) {
            $spec = $args[$i + 1]; $idx = $spec.LastIndexOf(':')
            $contPart = if ($idx -gt 0) { $spec.Substring($idx + 1) } else { '' }
            if ($contPart -eq '/backup') { $dst = $spec.Substring(0, $idx) }
        }
    }
    if ($mode -ne 'tarfail' -and $dst) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        $tarBytes = [byte[]](31,139,8,0,0,0,0,0,0,3)
        [IO.File]::WriteAllBytes((Join-Path $dst 'scan-artifacts.tar.gz'), $tarBytes)
    }
    exit 0
}
if ($c0 -eq 'compose') {
    switch ($c1) {
        'up' { if ($mode -eq 'wontstart') { exit 1 }; exit 0 }
        'cp' {
            if ($mode -eq 'copyfail') { exit 1 }
            $dst = if ($args.Count -gt 3) { $args[3] } else { '' }
            if ((Test-Path $fakeDump) -and $dst) { Copy-Item $fakeDump $dst -Force }
            exit 0
        }
        'exec' {
            $joined = $args -join ' '
            if ($joined -match 'pg_isready') {
                if ($mode -eq 'neverready') { Start-Sleep -Milliseconds 100; exit 1 }
                exit 0
            }
            if ($joined -match 'pg_dump') {
                if ($mode -eq 'dumpfail') {
                    [Console]::Error.WriteLine('pg_dump: error: could not write to output file')
                    exit 1
                }
                if ($mode -eq 'emptydump') {
                    [IO.File]::WriteAllBytes($fakeDump, [byte[]]@())
                    exit 0
                }
                $payload = [System.Text.Encoding]::UTF8.GetString(
                    [Convert]::FromBase64String($env:P29_DUMP_B64))
                [IO.File]::WriteAllBytes($fakeDump,
                    [System.Text.Encoding]::UTF8.GetBytes($payload))
                exit 0
            }
            if ($joined -match ' rm ') {
                if (Test-Path $fakeDump) {
                    Remove-Item $fakeDump -Force -ErrorAction SilentlyContinue
                }
                exit 0
            }
            exit 0
        }
        'config' {
            @{ services = @{ db = @{ image = 'postgres:16' } } } |
                ConvertTo-Json -Depth 5 -Compress | Write-Output
            exit 0
        }
        'down' { Write-ShimLog 'TEARDOWN_DOWN'; exit 0 }
        default { exit 0 }
    }
}
exit 0
"""

DUMP_B64 = base64.b64encode(EXPECTED_DUMP).decode("ascii")


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
    (mini / ".env").write_text("POSTGRES_USER=wardress\nPOSTGRES_DB=wardress\n", encoding="ascii")

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
        shell: str | None = None,
        with_backup_path: bool = False,
    ):
        bdir = tmp_path / "backups" / tag
        log = tmp_path / f"invocations_{tag}.log"
        env = os.environ.copy()
        env["P29_MODE"] = mode
        env["P29_LOG"] = str(log)
        env["P29_CONTAINER_DIR"] = str(tmp_path / f"fakecontainer_{tag}")
        os.makedirs(env["P29_CONTAINER_DIR"], exist_ok=True)
        env["P29_DUMP_B64"] = DUMP_B64
        env["PATH"] = str(bin_dir) + os.path.pathsep + env.get("PATH", "")

        argv = [
            (shell or PWSH),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(mini / "scripts" / script),
        ]
        if with_backup_path:
            argv += ["-Force", "-BackupPath", str(bdir)]
        argv += list(extra)

        sw = time.monotonic()
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        elapsed = time.monotonic() - sw
        output = proc.stdout + "\n" + (proc.stderr or "")
        dump_file = bdir / "database.sql"
        restore_file = bdir / "RESTORE.txt"
        return SimpleNamespace(
            returncode=proc.returncode,
            output=output,
            elapsed=elapsed,
            log=log,
            bdir=bdir,
            dump=(dump_file.read_bytes() if dump_file.exists() else None),
            restore=(
                restore_file.read_text(encoding="utf-8-sig") if restore_file.exists() else None
            ),
        )

    def run_uninstall(
        mode: str, tag: str, extra=(), timeout: float = 240, shell: str | None = None
    ):
        return run(
            "uninstall.ps1",
            mode,
            tag,
            extra=extra,
            timeout=timeout,
            shell=shell,
            with_backup_path=True,
        )

    return SimpleNamespace(run=run, run_uninstall=run_uninstall, mini=mini, tmp_path=tmp_path)


def teardown_counts(log: Path) -> tuple[int, int]:
    """(down calls, volume rm calls) observed by the shim."""
    if not log.exists():
        return 0, 0
    down = 0
    volume_rm = 0
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("CALL|"):
            rest = line[len("CALL|") :]
            if rest.startswith("compose down"):
                down += 1
            elif rest.startswith("volume rm"):
                volume_rm += 1
    return down, volume_rm


# ---------------------------------------------------------------------------
# Finding: backup/restore silently destroys all non-ASCII content
# ---------------------------------------------------------------------------


def test_dump_is_byte_exact_under_pwsh(sandbox, desktop_shortcut_guard):
    """Parity guard: the fixed pipeline preserves producer bytes under pwsh 7
    (the old redirect also happened to pass here on UTF-8 consoles, so this
    pins the mechanism rather than proving the fix alone)."""
    r = sandbox.run_uninstall("ok", "bytes_pwsh")
    assert r.returncode == 0, r.output
    assert r.dump == EXPECTED_DUMP


@pytest.mark.skipif(
    PS51 is None,
    reason="Windows PowerShell 5.1 not present on this platform; verified "
    "manually on Windows (pre-fix produced UTF-16LE+BOM mojibake) and "
    "automatically everywhere under pwsh, which shares the mechanism",
)
def test_dump_is_byte_exact_under_windows_powershell_51(sandbox, desktop_shortcut_guard):
    """THE failing-before proof for the encoding fix: under the documented
    invocation shell (powershell.exe 5.1) the old `> $dumpFile` redirect
    re-encoded the stream through PowerShell's text layer (observed live:
    a 188-byte UTF-8 payload became 388-byte UTF-16LE+BOM, with content
    loss whenever the ambient console codepage is not UTF-8). The
    container-side dump + compose cp pipeline must land the exact producer
    bytes regardless of host shell."""
    r = sandbox.run_uninstall("ok", "bytes_51", shell=PS51)
    assert r.returncode == 0, r.output
    assert r.dump is not None, "database.sql missing under PS 5.1"
    assert r.dump == EXPECTED_DUMP, (
        "database.sql was re-encoded by the host shell under Windows "
        f"PowerShell 5.1 ({len(r.dump)} bytes vs expected "
        f"{len(EXPECTED_DUMP)})"
    )


def test_restore_recipe_uses_container_copy_not_host_piping(sandbox, desktop_shortcut_guard):
    """RESTORE.txt must never instruct piping the dump through a host shell
    (Get-Content | psql flattens non-ASCII to '?' under PS 5.1's ASCII
    $OutputEncoding); it must use compose cp plus in-container psql -f."""
    r = sandbox.run_uninstall("ok", "recipe")
    assert r.returncode == 0, r.output
    assert r.restore is not None
    restore_step = r.restore.split("To restore into a fresh install")[1]
    assert "docker compose cp" in restore_step
    assert "-f /tmp/restore.sql" in restore_step
    assert "Get-Content" not in restore_step
    # Contents description survives (Phase 13 contract substring intact).
    contents_section = r.restore.split("To restore into a fresh install")[0]
    assert "database.sql            Logical" in contents_section


def test_copy_failure_blocks_teardown_with_named_reason(sandbox, desktop_shortcut_guard):
    """A dump that succeeds in-container but cannot be copied out is an
    incomplete backup and must gate the destructive phase (Phase 13's
    contract extended to the new pipeline stage)."""
    r = sandbox.run_uninstall("copyfail", "copyfail")
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "INCOMPLETE" in r.output
    assert "(database dump could not be copied out)" in r.output
    assert "Backup completed successfully" not in r.output


def test_empty_dump_rejected_by_verification(sandbox, desktop_shortcut_guard):
    """An exit-0 pg_dump producing zero bytes must not count as a captured
    backup: the sanity check (plain-format dumps begin with '--') rejects
    it and the completeness gate blocks teardown."""
    r = sandbox.run_uninstall("emptydump", "emptydump")
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "(database dump verification failed)" in r.output
    assert r.dump is None  # the rejected file was removed, never counted


def test_pg_dump_failure_keeps_historical_reason_and_gate(sandbox, desktop_shortcut_guard):
    """Phase 13 interplay pin: a failing pg_dump still reports the exact
    historical reason string and still blocks teardown after the rewrite."""
    r = sandbox.run_uninstall("dumpfail", "dumpfail29")
    assert r.returncode == 1
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0
    assert "database.sql (pg_dump failed)" in r.output
    assert r.restore is not None
    assert "WARNING: THIS BACKUP IS INCOMPLETE" in r.restore


# ---------------------------------------------------------------------------
# Finding: entry-point scripts hang forever when the Docker CLI wedges
# ---------------------------------------------------------------------------


HELPER_PROBE_PS = """
param([string]$LibPath)
. $LibPath
$pwshExe = (Get-Command pwsh).Source
$r1 = Invoke-NativeWithDeadline $pwshExe @("-NoProfile", "-Command", "exit 7") 15
$r2 = Invoke-NativeWithDeadline $pwshExe @("-NoProfile", "-Command", "exit 0") 15
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$r3 = Invoke-NativeWithDeadline $pwshExe @("-NoProfile", "-Command", "Start-Sleep -Seconds 60") 3
$elapsed = [int]$sw.Elapsed.TotalSeconds
Write-Output ("RESULT|r1=$r1|r2=$r2|r3IsNull=" + ($null -eq $r3) + "|elapsed=$elapsed")
"""


def _run_helper_probe() -> dict[str, str]:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "probe.ps1"
        probe.write_text(HELPER_PROBE_PS, encoding="utf-8")
        out = subprocess.run(
            [
                PWSH,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(probe),
                "-LibPath",
                str(REPO_ROOT / "scripts" / "lib.ps1"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        assert out.returncode == 0, out.stderr
        for line in out.stdout.splitlines():
            if line.startswith("RESULT|"):
                return dict(kv.split("=", 1) for kv in line.strip().split("|")[1:])
        raise AssertionError(f"probe produced no RESULT line: {out.stdout!r}")


def test_deadline_helper_returns_false_true_and_null_on_timeout():
    """Unit contract of Invoke-NativeWithDeadline: nonzero exit -> False,
    zero exit -> True, deadline blowout -> null within the bound."""
    fields = _run_helper_probe()
    assert fields["r1"] == "False"
    assert fields["r2"] == "True"
    assert fields["r3IsNull"] == "True"
    assert int(fields["elapsed"]) < 10, "deadline was not honored"


@pytest.mark.parametrize("script", ["validate.ps1", "install.ps1"])
def test_wedged_docker_preflight_fails_fast_with_readable_message(sandbox, script):
    """A Docker CLI wedged at the first engine probe must end the entry-point
    script within the deadline with the actionable wedged message (pre-fix
    these scripts hung indefinitely and had to be killed externally)."""
    r = sandbox.run(script, "hang_info", f"wedge_{script}", timeout=150)
    assert r.elapsed < 120, f"{script} did not fail fast (took {r.elapsed:.0f}s)"
    assert r.returncode != 0
    assert "did not respond within" in r.output


def test_wedged_uninstall_preflight_never_reaches_teardown(sandbox, desktop_shortcut_guard):
    """Same wedge through the uninstaller: bounded failure BEFORE any
    destructive call (zero compose-down / volume-rm invocations)."""
    r = sandbox.run_uninstall("hang_info", "wedge_uninstall", extra=("-SkipBackup",), timeout=150)
    assert r.elapsed < 120, f"uninstall did not fail fast (took {r.elapsed:.0f}s)"
    assert r.returncode == 1
    assert "did not respond within" in r.output
    down, volume_rm = teardown_counts(r.log)
    assert down == 0 and volume_rm == 0


def test_engine_down_still_reports_the_distinct_message(sandbox):
    """Behavior-preservation guard: a fast-failing engine probe keeps the
    historical 'engine is not running' message (distinct from the new
    wedged message); this passes both before and after the change."""
    r = sandbox.run_uninstall("enginedown", "enginedown", extra=("-SkipBackup",))
    assert r.returncode == 1
    assert "engine is not running" in r.output
    assert "did not respond within" not in r.output


def test_diagnostics_bounded_under_wedge(sandbox, tmp_path):
    """diagnostics.ps1's docker info sat behind a plain try/catch, which can
    catch errors but not hangs; it must now record the wedged condition and
    finish inside the deadline."""
    out_path = tmp_path / "diag_bundle.txt"
    r = sandbox.run(
        "diagnostics.ps1",
        "hang_info",
        "wedge_diag",
        extra=("-OutputPath", str(out_path)),
        timeout=150,
    )
    assert r.elapsed < 120, f"diagnostics did not finish (took {r.elapsed:.0f}s)"
    bundle = out_path.read_text(encoding="utf-8-sig")
    assert "did not respond within 30 seconds" in bundle


# ---------------------------------------------------------------------------
# Finding: ADMIN_RESET_PASSWORD emergency-recovery knob is unreachable
# ---------------------------------------------------------------------------


def test_compose_forwards_admin_reset_password_to_app():
    """The app service environment must forward ADMIN_RESET_PASSWORD so the
    documented .env-based recovery flow reaches the container (before the
    fix it was silently dropped by compose's fixed allow-list, making the
    tool's own printed hint a no-op)."""
    text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    lines = text.splitlines()
    app_block = None
    for i, line in enumerate(lines):
        if line.startswith("  app:"):
            block = []
            for following in lines[i + 1 :]:
                if following.startswith("  ") and not following.startswith("   "):
                    break  # next top-level service key at two-space indent
                block.append(following)
            app_block = "\n".join(block)
            break
    assert app_block is not None, "could not locate the app service block"
    assert "ADMIN_RESET_PASSWORD" in app_block


def test_env_example_documents_the_reset_knob():
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ADMIN_RESET_PASSWORD=false" in example


async def test_seed_hint_prints_a_working_recovery_command(db_factory, monkeypatch, capsys):
    """The already-exists branch must print a recovery procedure whose
    commands actually work end to end (compose forwarding + transient -e
    override), replacing the old hint that could only ever no-op."""
    import app.seed_admin as seed_admin

    monkeypatch.setenv("ADMIN_EMAIL", "hintflow@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "hint-flow-password-123")
    monkeypatch.delenv("ADMIN_RESET_PASSWORD", raising=False)

    assert await seed_admin.seed() == 0
    capsys.readouterr()

    assert await seed_admin.seed() == 0
    out = capsys.readouterr().out
    assert "User hintflow@example.com already exists." in out
    assert "(set ADMIN_RESET_PASSWORD=true to reset)" not in out
    assert "docker compose up -d app" in out
    assert "exec -T -e ADMIN_RESET_PASSWORD=true app python -m app.seed_admin" in out


async def test_seed_reset_flow_end_to_end(db_factory, monkeypatch):
    """Functional coverage of the emergency path the docs now describe:
    create -> deactivate + issue session -> reset flag flips password,
    reactivates the account and revokes sessions; without the flag the
    password in the environment is NEVER silently applied."""
    from sqlalchemy import select

    import app.seed_admin as seed_admin
    from app.models import RefreshToken, User
    from app.security import verify_password

    email = "resetflow@example.com"
    monkeypatch.setenv("ADMIN_EMAIL", email)
    monkeypatch.setenv("ADMIN_RESET_PASSWORD", "")

    monkeypatch.setenv("ADMIN_PASSWORD", "first-password-123")
    assert await seed_admin.seed() == 0

    async with db_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        assert user.role.value == "admin"
        first_hash = user.password_hash
        user.is_active = False
        db.add(
            RefreshToken(
                user_id=user.id,
                token_hash="a" * 64,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.commit()

    monkeypatch.setenv("ADMIN_RESET_PASSWORD", "true")
    monkeypatch.setenv("ADMIN_PASSWORD", "second-password-456")
    assert await seed_admin.seed() == 0

    async with db_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user.password_hash != first_hash
        assert verify_password(user.password_hash, "second-password-456")
        assert user.is_active is True
        tokens = (
            await db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id))
        ).all()
        assert tokens
        assert all(t.revoked_at is not None for t in tokens)

    monkeypatch.setenv("ADMIN_RESET_PASSWORD", "")
    monkeypatch.setenv("ADMIN_PASSWORD", "third-password-789")
    assert await seed_admin.seed() == 0

    async with db_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert verify_password(user.password_hash, "second-password-456")
        assert not verify_password(user.password_hash, "third-password-789")
