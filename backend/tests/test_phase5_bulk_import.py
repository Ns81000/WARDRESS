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
