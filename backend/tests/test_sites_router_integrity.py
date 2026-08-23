"""Sites-router integrity & performance proofs.

Three defect classes, one module:
- sites.url uniqueness — single-create had no dedup check and bulk
  import's snapshot dedup had no DB backstop, so concurrent creators all
  won (twins doubled scans/alerts/remediation firings);
- GET /api/sites issued up to 2N+1 queries;
- the bulk-import CSV parser ran with quoting=QUOTE_NONE, so standard
  RFC-4180 (spreadsheet-export) files failed wholesale.

Concurrency tests drive the real app against real Postgres; the
commit-window shim only guarantees the racers overlap (pre-fix they all
insert before anyone commits), while post-fix outcomes are arbitrated by
the uq_sites_url unique index in the database, not by the shim.
"""

import asyncio
import os
import subprocess
import sys
import uuid as uuid_mod
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Baseline, BaselineStatus, Site, utcnow
from app.routers import imports as imports_router
from app.services import ConflictError

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


@pytest.fixture(autouse=True)
def _stub_ssrf(monkeypatch):
    """Hermetic policy check: these tests exercise uniqueness/perf/parsing,
    not the SSRF policy, so the check is a no-op (no DNS, nothing blocked).
    Loopback URLs keep the tests off the network."""

    def fake_assert(url, *, allow_private_networks=False):
        return None

    monkeypatch.setattr(imports_router, "assert_url_allowed", fake_assert)
    from app import services

    monkeypatch.setattr(services, "assert_url_allowed", fake_assert)


@pytest.fixture
def widen_commit_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guarantee racers overlap: every commit waits, so all participants
    insert before any of them commits (post-fix the DB still arbitrates)."""
    original = AsyncSession.commit

    async def slowed(self: AsyncSession):
        await asyncio.sleep(0.05)
        return await original(self)

    monkeypatch.setattr(AsyncSession, "commit", slowed)


# --- Finding: No uniqueness on sites.url -----------------------------------


class TestUrlUniqueness:
    async def test_single_create_duplicate_url_conflicts(self, client, auth_headers, db_factory):
        first = await client.post(
            "/api/sites",
            headers=auth_headers,
            json={"name": "Original", "url": "http://127.0.0.1/dup-single"},
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            "/api/sites",
            headers=auth_headers,
            json={"name": "Twin", "url": "http://127.0.0.1/dup-single"},
        )
        assert second.status_code == 409, second.text
        assert "already exists" in second.json()["detail"]

        async with db_factory() as db:
            count = await db.scalar(
                select(text("count(*)"))
                .select_from(Site)
                .where(Site.url == "http://127.0.0.1/dup-single")
            )
        assert count == 1

    async def test_service_create_site_duplicate_raises_conflict(self, db_factory, admin_user):
        """The service-level contract the agent tool and Telegram bot
        inherit: a duplicate URL surfaces as ConflictError with the
        user-safe message, not a raw IntegrityError."""
        from app import services

        async with db_factory() as db:
            await services.create_site(
                db,
                name="First",
                url="http://127.0.0.1/dup-service",
                actor=admin_user,
                via="test",
            )
        async with db_factory() as db:
            with pytest.raises(ConflictError) as excinfo:
                await services.create_site(
                    db,
                    name="Second",
                    url="http://127.0.0.1/dup-service",
                    actor=admin_user,
                    via="test",
                )
        assert "already exists" in str(excinfo.value.message)

    async def test_concurrent_creates_exactly_one_winner(
        self, client, auth_headers, db_factory, widen_commit_window
    ):
        url = "http://127.0.0.1/race-create"
        barrier = asyncio.Barrier(6)

        async def racer():
            async with barrier:
                return await client.post(
                    "/api/sites",
                    headers=auth_headers,
                    json={"name": "Racer", "url": url},
                )

        responses = await asyncio.gather(*[racer() for _ in range(6)])
        codes = sorted(r.status_code for r in responses)
        assert codes.count(201) == 1, codes
        assert codes.count(409) == 5, codes

        async with db_factory() as db:
            count = await db.scalar(
                select(text("count(*)")).select_from(Site).where(Site.url == url)
            )
        assert count == 1

    async def test_concurrent_bulk_imports_no_duplicate_rows(
        self, client, auth_headers, db_factory, widen_commit_window
    ):
        csv_text = "\n".join(f"http://127.0.0.1/race-import-{i}" for i in range(5))
        barrier = asyncio.Barrier(8)

        async def importer():
            async with barrier:
                resp = await client.post(
                    "/api/sites/bulk-import",
                    headers=auth_headers,
                    json={"csv_text": csv_text},
                )
            assert resp.status_code == 200, resp.text
            return resp.json()

        results = await asyncio.gather(*[importer() for _ in range(8)])

        # Exactly five sites exist overall — one per URL, no matter how the
        # racers interleaved.
        async with db_factory() as db:
            counts = (await db.execute(text("SELECT url, count(*) FROM sites GROUP BY url"))).all()
        assert {url: int(n) for url, n in counts} == {
            f"http://127.0.0.1/race-import-{i}": 1 for i in range(5)
        }

        # Honest reporting: every row lands created-or-skipped (never a
        # generic error), and the created tally sums to exactly five.
        all_rows = [row for body in results for row in body["results"]]
        assert len(all_rows) == 40
        assert all(r["status"] in ("created", "skipped") for r in all_rows), all_rows
        assert sum(1 for r in all_rows if r["status"] == "created") == 5

    async def test_padded_import_row_skips_existing_site(self, client, auth_headers):
        """The dedup comparison stays exact-string-after-strip: whitespace
        around a CSV cell matches the stored URL."""
        await client.post(
            "/api/sites",
            headers=auth_headers,
            json={"name": "Existing", "url": "http://127.0.0.1/padded-match"},
        )
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"csv_text": "  http://127.0.0.1/padded-match  ,Padded"},
        )
        body = resp.json()
        assert body["created"] == 0
        assert body["skipped"] == 1
        assert "already exists" in body["results"][0]["detail"]

    async def test_unique_index_backs_the_contract(self, engine, db_factory):
        async with engine.begin() as conn:
            indexes = (
                await conn.execute(
                    text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'sites'")
                )
            ).all()
        names = {r.indexname for r in indexes}
        assert "uq_sites_url" in names
        assert "ix_sites_url" not in names
        assert any("unique" in r.indexdef.lower() for r in indexes if r.indexname == "uq_sites_url")

        from sqlalchemy.exc import IntegrityError

        async with db_factory() as db:
            db.add(Site(name="A", url="http://127.0.0.1/raw-backstop"))
            await db.flush()
            db.add(Site(name="B", url="http://127.0.0.1/raw-backstop"))
            with pytest.raises(IntegrityError):
                await db.flush()

    async def test_migration_repairs_preexisting_duplicates_keep_oldest(self, engine):
        """The shipped migration collapses pre-existing twins (keeping the
        earliest-created site per URL) before building the unique index —
        exercised here by downgrading, planting duplicates, and upgrading."""
        env = dict(os.environ)
        # str(engine.url) masks the password; render it in full for the subprocess.
        env["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)

        def alembic(*args: str) -> None:
            proc = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=str(BACKEND_DIR),
                env=env,
                capture_output=True,
                timeout=300,
            )
            assert proc.returncode == 0, (
                proc.stdout.decode("utf-8", "replace")[-1500:]
                + proc.stderr.decode("utf-8", "replace")[-1500:]
            )

        async def insert_site(site_id: str, name: str, created_at: datetime) -> None:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO sites (id, name, url, allow_private_networks,"
                        " is_active, flag_threshold, auto_scan_enabled,"
                        " scan_interval_minutes, created_at)"
                        " VALUES (:id, :name, 'http://127.0.0.1/mig-dup', false, true,"
                        " 0.5, true, 60, :created_at)"
                    ),
                    {"id": site_id, "name": name, "created_at": created_at},
                )

        async def count_dup() -> int:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text("SELECT count(*) FROM sites WHERE url = 'http://127.0.0.1/mig-dup'")
                )
                return int(result.scalar_one())

        async def keeper_name() -> str | None:
            async with engine.begin() as conn:
                result = await conn.execute(
                    text("SELECT name FROM sites WHERE url = 'http://127.0.0.1/mig-dup'")
                )
                return result.scalar_one_or_none()

        # Anchor to the repair revision itself (not "-1" from head): later
        # migrations may be appended after i3j4k5l6m7n8, and the test needs
        # the schema as it was BEFORE the dedupe/unique-index revision.
        alembic("downgrade", "i3j4k5l6m7n8-1")

        try:
            await insert_site(
                str(uuid_mod.UUID(int=1)), "old-keeper", datetime(2026, 1, 1, tzinfo=UTC)
            )
            await insert_site(
                str(uuid_mod.UUID(int=2)), "twin-middle", datetime(2026, 6, 1, tzinfo=UTC)
            )
            await insert_site(
                str(uuid_mod.UUID(int=3)), "twin-newest", datetime(2026, 8, 1, tzinfo=UTC)
            )
            assert await count_dup() == 3
            alembic("upgrade", "head")
        finally:
            # Never leave the shared harness database below head, even if
            # an assertion above fired mid-way.
            alembic("upgrade", "head")

        assert await count_dup() == 1
        assert await keeper_name() == "old-keeper"

        async with engine.begin() as conn:
            indexes = (
                await conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'sites'")
                )
            ).all()
        assert "uq_sites_url" in {r.indexname for r in indexes}


# --- Finding: GET /api/sites runs 1+2N queries -----------------------------


async def _seed_perf_fleet(db_factory, n: int) -> None:
    async with db_factory() as db:
        for i in range(n):
            site = Site(name=f"Fleet {i}", url=f"http://127.0.0.1/perf-{i}")
            db.add(site)
            await db.flush()
            kind = i % 3
            if kind == 0:
                db.add(
                    Baseline(
                        site_id=site.id,
                        status=BaselineStatus.ready,
                        is_current=True,
                        content_hash="x",
                    )
                )
            elif kind == 1:
                db.add(Baseline(site_id=site.id, status=BaselineStatus.pending))
        await db.commit()


class TestListSitesPerformance:
    async def test_query_count_is_constant_in_fleet_size(
        self, client, auth_headers, engine, db_factory
    ):
        await _seed_perf_fleet(db_factory, 30)

        selects = {"n": 0}

        def counter(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects["n"] += 1

        event.listen(engine.sync_engine, "before_cursor_execute", counter)
        try:
            resp = await client.get("/api/sites", headers=auth_headers)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", counter)

        assert resp.status_code == 200
        assert len(resp.json()) == 30
        # Constant budget: user lookup + sites + current-baselines +
        # newest-fallbacks. The pre-fix endpoint issued 52 SELECTs here.
        assert selects["n"] <= 5, selects["n"]

    async def test_baseline_semantics_preserved(self, client, auth_headers, db_factory):
        """current-baseline preferred over newer attempts; newest attempt
        surfaced when nothing is current; empty stays null; ordering is
        newest-site-first. (Regression guard — true before and after.)"""
        async with db_factory() as db:
            has_current = Site(name="HasCurrent", url="http://127.0.0.1/sem-current")
            only_pending = Site(name="OnlyPending", url="http://127.0.0.1/sem-pending")
            no_baseline = Site(name="NoBaseline", url="http://127.0.0.1/sem-none")
            db.add_all([has_current, only_pending, no_baseline])
            await db.flush()
            current = Baseline(
                site_id=has_current.id,
                status=BaselineStatus.ready,
                is_current=True,
                content_hash="x",
                created_at=utcnow(),
            )
            newer_attempt = Baseline(
                site_id=has_current.id,
                status=BaselineStatus.pending,
                created_at=utcnow(),
            )
            pending = Baseline(site_id=only_pending.id, status=BaselineStatus.pending)
            db.add_all([current, newer_attempt, pending])
            await db.commit()
            current_id, pending_id = current.id, pending.id
            ids = {s.name: s.id for s in (has_current, only_pending, no_baseline)}

        resp = await client.get("/api/sites", headers=auth_headers)
        body = resp.json()
        by_id = {row["id"]: row for row in body}

        assert by_id[str(ids["HasCurrent"])]["baseline_status"] == "ready"
        assert by_id[str(ids["HasCurrent"])]["baseline_id"] == str(current_id)
        assert by_id[str(ids["OnlyPending"])]["baseline_status"] == "pending"
        assert by_id[str(ids["OnlyPending"])]["baseline_id"] == str(pending_id)
        assert by_id[str(ids["NoBaseline"])]["baseline_status"] is None
        assert by_id[str(ids["NoBaseline"])]["baseline_id"] is None


# --- Finding: Bulk-import CSV parser uses QUOTE_NONE -----------------------


class TestCsvQuoting:
    async def test_rfc4180_quoted_row_created(self, client, auth_headers):
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"csv_text": '"http://127.0.0.1/quoted-a","Quoted Site"\n'},
        )
        body = resp.json()
        assert body["created"] == 1, body
        row = body["results"][0]
        assert row["status"] == "created"
        assert row["url"] == "http://127.0.0.1/quoted-a"
        assert row["name"] == "Quoted Site"

    async def test_rfc4180_quoted_header_line_skipped(self, client, auth_headers):
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"csv_text": '"url","name"\n"http://127.0.0.1/quoted-b","Second"\n'},
        )
        body = resp.json()
        assert body["total_rows"] == 1, body
        assert body["errors"] == 0
        assert body["created"] == 1
        assert body["results"][0]["url"] == "http://127.0.0.1/quoted-b"

    async def test_quoted_comma_inside_name_preserved(self, client, auth_headers):
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"csv_text": 'http://127.0.0.1/comma-a,"Name with, comma"\n'},
        )
        body = resp.json()
        assert body["created"] == 1, body
        assert body["results"][0]["name"] == "Name with, comma"

    async def test_unquoted_comma_still_splits_gracefully(self, client, auth_headers):
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"csv_text": "http://127.0.0.1/plain-a,Plain Name,extra-cells\n"},
        )
        body = resp.json()
        assert body["created"] == 1, body
        assert body["results"][0]["name"] == "Plain Name"

    async def test_malformed_quote_degrades_without_false_creates(
        self, client, auth_headers, db_factory
    ):
        """An unterminated quote consumes the following line (standard csv
        behavior). The request must neither crash nor store the merged
        garbage as a site — the second line is lost with it, which is the
        documented tradeoff of RFC-4180 parsing on malformed input."""
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={
                "csv_text": '"http://127.0.0.1/broken,Unterminated\n'
                "http://127.0.0.1/should-not-exist,Fine\n"
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 0
        assert body["total_rows"] == 1
        assert body["errors"] == 1
        assert "invalid characters" in body["results"][0]["detail"]
        async with db_factory() as db:
            count = await db.scalar(select(text("count(*)")).select_from(Site))
        assert count == 0


# --- Fix-mechanics guards --------------------------------------------------


class TestViolationClassification:
    def test_sqlstate_predicates(self):
        from sqlalchemy.exc import IntegrityError

        from app.services import concurrent_write_aborted, sites_url_unique_violation

        class _Orig(Exception):
            pass

        def wrapped(sqlstate: str | None, constraint: str | None) -> IntegrityError:
            orig = _Orig()
            if sqlstate is not None:
                orig.sqlstate = sqlstate  # type: ignore[attr-defined]
            if constraint is not None:
                orig.constraint_name = constraint  # type: ignore[attr-defined]
            return IntegrityError("INSERT failed", None, orig)

        assert sites_url_unique_violation(wrapped("23505", "uq_sites_url"))
        assert sites_url_unique_violation(wrapped("23505", None))
        assert not sites_url_unique_violation(wrapped("23505", "some_other_constraint"))
        assert not sites_url_unique_violation(wrapped("22P02", None))
        assert not sites_url_unique_violation(SQLAlchemyError("no orig"))

        assert concurrent_write_aborted(wrapped("40P01", None))
        assert concurrent_write_aborted(wrapped("40001", None))
        assert not concurrent_write_aborted(wrapped("23505", "uq_sites_url"))
