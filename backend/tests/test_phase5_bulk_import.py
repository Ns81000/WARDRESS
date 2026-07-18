"""Bulk site import — CSV + sitemap, per-row results (Phase 5, §7)."""

import pytest
from sqlalchemy import func, select

from app.models import Site
from app.routers import imports as imports_router


@pytest.fixture(autouse=True)
def _stub_enqueues(stub_all_enqueues):
    return stub_all_enqueues


@pytest.fixture(autouse=True)
def _stub_ssrf(monkeypatch):
    """Keep bulk-import tests hermetic: replace the real DNS-resolving
    SSRF check with a fake that blocks only loopback/private literals, so
    tests neither hit the network nor depend on DNS."""

    def fake_assert(url, *, allow_private_networks=False):
        from urllib.parse import urlparse

        from app.ssrf import SSRFBlockedError

        host = urlparse(url).hostname or ""
        if not allow_private_networks and (host.startswith("127.") or host == "localhost"):
            raise SSRFBlockedError(f"Address {host} is in a blocked range")

    monkeypatch.setattr(imports_router, "assert_url_allowed", fake_assert)


class TestCsvImport:
    async def test_mixed_rows_report_per_row(self, client, auth_headers, db_factory):
        csv = "\n".join(
            [
                "url,name",  # header, skipped
                "https://a.example.com,Site A",
                "https://b.example.com",
                "not-a-url",
                "https://a.example.com,Dup",  # duplicate within batch
                "http://127.0.0.1/,Internal",  # SSRF-blocked
            ]
        )
        resp = await client.post(
            "/api/sites/bulk-import", headers=auth_headers, json={"csv_text": csv}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 2
        assert body["skipped"] == 1  # the in-batch duplicate
        assert body["errors"] == 2  # not-a-url + loopback
        by_status = {r["url"]: r["status"] for r in body["results"]}
        # First occurrence of a.example.com created; the later duplicate row
        # (same URL) is the one that reports skipped.
        statuses = [r["status"] for r in body["results"]]
        assert statuses == ["created", "created", "error", "skipped", "error"]
        assert by_status["not-a-url"] == "error"

        async with db_factory() as db:
            count = await db.scalar(select(func.count()).select_from(Site))
            assert count == 2

    async def test_existing_url_skipped(self, client, auth_headers):
        await client.post(
            "/api/sites",
            headers=auth_headers,
            json={"name": "Existing", "url": "https://example.com/exists"},
        )
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"csv_text": "https://example.com/exists"},
        )
        body = resp.json()
        assert body["skipped"] == 1
        assert body["results"][0]["detail"] and "already exists" in body["results"][0]["detail"]

    async def test_empty_csv_rejected(self, client, auth_headers):
        resp = await client.post(
            "/api/sites/bulk-import", headers=auth_headers, json={"csv_text": "\n\n"}
        )
        assert resp.status_code == 422

    async def test_both_sources_rejected(self, client, auth_headers):
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={
                "csv_text": "https://a.example.com",
                "sitemap_url": "https://a.example.com/sitemap.xml",
            },
        )
        assert resp.status_code == 422


class TestSitemapImport:
    async def test_sitemap_urls_parsed(self, client, auth_headers, monkeypatch):
        sitemap = b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://site.example.com/</loc></url>
          <url><loc>https://site.example.com/about</loc></url>
        </urlset>"""

        async def fake_crawl(sitemap_url, *, allow_private_networks):
            from app.routers.imports import _extract_sitemap_urls

            pages, _ = _extract_sitemap_urls(sitemap)
            return [(i, u, None) for i, u in enumerate(pages, start=1)]

        monkeypatch.setattr(imports_router, "_crawl_sitemap_impl", fake_crawl)
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={"sitemap_url": "https://site.example.com/sitemap.xml"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 2

    def test_extract_handles_sitemap_index(self):
        from app.routers.imports import _extract_sitemap_urls

        doc = b"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://x.example.com/sitemap1.xml</loc></sitemap>
        </sitemapindex>"""
        pages, children = _extract_sitemap_urls(doc)
        assert pages == []
        assert children == ["https://x.example.com/sitemap1.xml"]


class TestPerRowIsolation:
    """CRITICAL: a per-row DB error must not roll back the whole import
    (§11 — imports are never all-or-nothing)."""

    async def test_oversized_csv_name_is_truncated_not_errored(
        self, client, auth_headers, db_factory
    ):
        # A CSV-supplied name longer than Site.name's 200-char column must
        # be capped, not raise DataError. (SQLite doesn't enforce the width,
        # so this asserts the source-level cap that prevents the error on
        # Postgres.)
        long_name = "x" * 500
        csv = f"https://long.example.com,{long_name}"
        resp = await client.post(
            "/api/sites/bulk-import", headers=auth_headers, json={"csv_text": csv}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 1
        assert len(body["results"][0]["name"]) == 200

        async with db_factory() as db:
            site = await db.scalar(select(Site).where(Site.url == "https://long.example.com"))
            assert site is not None
            assert len(site.name) == 200

    async def test_one_failing_row_does_not_lose_the_others(
        self, client, auth_headers, db_factory, monkeypatch
    ):
        # Force a genuine DB-layer failure on exactly one row's flush and
        # confirm the SAVEPOINT isolates it: the other rows still commit.
        from sqlalchemy.exc import IntegrityError

        real_add = imports_router.Site

        class ExplodingSite(real_add):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                if kwargs.get("url") == "https://boom.example.com":
                    raise IntegrityError("forced", None, Exception("forced per-row failure"))
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(imports_router, "Site", ExplodingSite)

        csv = "\n".join(
            [
                "https://ok1.example.com",
                "https://boom.example.com",
                "https://ok2.example.com",
            ]
        )
        resp = await client.post(
            "/api/sites/bulk-import", headers=auth_headers, json={"csv_text": csv}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] == 2
        assert body["errors"] == 1
        by_url = {r["url"]: r for r in body["results"]}
        assert by_url["https://boom.example.com"]["status"] == "error"
        assert by_url["https://ok1.example.com"]["status"] == "created"
        assert by_url["https://ok2.example.com"]["status"] == "created"

        # The two good rows are actually persisted; the failing one is not.
        async with db_factory() as db:
            count = await db.scalar(select(func.count()).select_from(Site))
            assert count == 2
            boom = await db.scalar(select(Site).where(Site.url == "https://boom.example.com"))
            assert boom is None


class TestPrivateNetworksSitemapAdminGate:
    """Decision 8-real: allow_private_networks on a sitemap crawl is
    admin-only (it turns the server into an internal-network fetcher);
    analysts keep it for CSV imports, which never crawl."""

    async def test_analyst_sitemap_with_private_flag_is_forbidden(
        self, client, analyst_headers, monkeypatch
    ):
        # Crawl must never run for a forbidden request — patch it to prove
        # the 403 fires before any fetch.
        async def fail_if_called(*args, **kwargs):
            raise AssertionError("crawl must not run for a forbidden request")

        monkeypatch.setattr(imports_router, "_crawl_sitemap_impl", fail_if_called)
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=analyst_headers,
            json={
                "sitemap_url": "https://site.example.com/sitemap.xml",
                "allow_private_networks": True,
            },
        )
        assert resp.status_code == 403, resp.text

    async def test_admin_sitemap_with_private_flag_is_allowed(
        self, client, auth_headers, monkeypatch
    ):
        async def fake_crawl(sitemap_url, *, allow_private_networks):
            assert allow_private_networks is True
            return [(1, "https://internal.example.com/page", None)]

        monkeypatch.setattr(imports_router, "_crawl_sitemap_impl", fake_crawl)
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=auth_headers,
            json={
                "sitemap_url": "https://site.example.com/sitemap.xml",
                "allow_private_networks": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 1

    async def test_analyst_csv_with_private_flag_still_works(self, client, analyst_headers):
        # CSV import never crawls, so the flag stays available to analysts.
        resp = await client.post(
            "/api/sites/bulk-import",
            headers=analyst_headers,
            json={
                "csv_text": "https://public.example.com",
                "allow_private_networks": True,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created"] == 1
