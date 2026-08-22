"""Self-tests for the Postgres test harness itself (Phase 1 finding).

These pin the property the old SQLite/create_all harness could not
provide: the test schema IS the migration chain's schema, so objects
declared only in Alembic revisions exist here and their constraints
actually fire. Equivalent assertions executed against the old harness
failed: model metadata lacks ix_scans_one_inflight_per_site, SQLite
stored a 400-char value in VARCHAR(256), and it accepted two
simultaneous in-flight scans on one site.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from db_harness import HarnessError, resolve_test_database_url
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, Base, Scan, ScanStatus, Site

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def test_schema_is_at_migration_head(engine):
    expected = ScriptDirectory.from_config(
        AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    ).get_current_head()
    async with engine.connect() as conn:
        version = (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar()
    assert version == expected


async def test_migration_only_inflight_index_exists_and_is_partial(engine):
    # The index must come from migrations, not ORM metadata - that split is
    # exactly what the old create_all harness could never represent.
    model_indexes = {ix.name for t in Base.metadata.tables.values() for ix in t.indexes}
    assert "ix_scans_one_inflight_per_site" not in model_indexes
    async with engine.connect() as conn:
        definition = (
            await conn.execute(
                sa.text(
                    "SELECT indexdef FROM pg_indexes"
                    " WHERE indexname = 'ix_scans_one_inflight_per_site'"
                )
            )
        ).scalar()
    assert definition is not None
    assert "WHERE" in definition and "status" in definition


async def test_second_pending_scan_for_site_rejected_while_history_scan_allowed(engine):
    async with engine.begin() as conn:
        inserted = await conn.execute(
            sa.insert(Site.__table__).values(name="harness", url="http://harness.invalid")
        )
        site_id = inserted.inserted_primary_key[0]
        await conn.execute(
            sa.insert(Scan.__table__).values(site_id=site_id, status=ScanStatus.pending)
        )
        # The predicate targets pending/running only: history rows coexist.
        await conn.execute(
            sa.insert(Scan.__table__).values(site_id=site_id, status=ScanStatus.completed)
        )
        # A rejected INSERT aborts the surrounding transaction, so attempt it
        # inside a SAVEPOINT whose rollback happens via the context manager's
        # exception path: the error must propagate OUT of begin_nested().
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(
                    sa.insert(Scan.__table__).values(site_id=site_id, status=ScanStatus.pending)
                )
        in_flight = (
            await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM scans"
                    " WHERE site_id = :sid AND status IN ('pending', 'running')"
                ),
                {"sid": site_id},
            )
        ).scalar()
    assert in_flight == 1


async def test_varchar256_width_enforced_on_audit_target_label(engine):
    # The asyncpg dialect wraps StringDataRightTruncationError (SQLSTATE
    # 22001) in a plain DBAPIError rather than DataError - assert on it.
    async with engine.begin() as conn:
        with pytest.raises(sa.exc.DBAPIError, match="value too long"):
            await conn.execute(
                sa.insert(AuditLog.__table__).values(
                    action="probe",
                    target_type="probe",
                    target_label="L" * 400,
                )
            )


_MARKER = "phase1-harness-isolation-marker"


async def test_isolation_step1_writes_marker_row(db_factory):
    # These two tests rely on pytest's in-file definition order: step 2 must
    # observe the database AFTER step 1's rows were wiped by fixture setup.
    async with db_factory() as db:
        db.add(AuditLog(action=_MARKER, target_type="probe"))
        await db.commit()


async def test_isolation_step2_marker_gone(db_factory):
    async with db_factory() as db:
        rows = (
            (await db.execute(sa.select(AuditLog).where(AuditLog.action == _MARKER)))
            .scalars()
            .all()
        )
    assert rows == []


def test_guard_refuses_non_test_database_name():
    with pytest.raises(HarnessError, match="wipes its table"):
        resolve_test_database_url(
            {"WARDRESS_TEST_DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/wardress"}
        )


def test_guard_refuses_non_asyncpg_scheme():
    with pytest.raises(HarnessError, match="postgresql\\+asyncpg"):
        resolve_test_database_url({"WARDRESS_TEST_DATABASE_URL": "sqlite+aiosqlite://"})


def test_guard_reports_malformed_url():
    with pytest.raises(HarnessError, match="not a valid database URL"):
        resolve_test_database_url(
            {"WARDRESS_TEST_DATABASE_URL": "postgresql+asyncpg://u:p@host:notaport/db_test"}
        )


def test_unsafe_allow_escape_hatch():
    resolved = resolve_test_database_url(
        {
            "WARDRESS_TEST_DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/production",
            "WARDRESS_TEST_DB_UNSAFE_ALLOW": "1",
        }
    )
    assert resolved.endswith("/production")


def test_default_url_satisfies_guard():
    assert resolve_test_database_url({}).endswith("wardress_test")
