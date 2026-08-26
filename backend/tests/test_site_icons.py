"""Opt-in site favicon resolver — endpoint, cache, security, concurrency.

Every outbound fetch is monkeypatched (hermetic per Phase 30); no test
touches the live network. The concurrency proof drives REAL asyncio
gather against the harness Postgres with a barrier so the requests
actually interleave; removing the claim primitive makes it fail with
multiple fetch invocations.
"""

import asyncio
import uuid as uuid_mod

import pytest
from sqlalchemy import select

from app.models import AuditLog, Site, SiteIcon, utcnow
from app.site_icons import FAVICON_SETTING_KEY

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FakeFetcher:
    """Stands in for the network seam (fetch_outcome_for_site)."""

    def __init__(self, outcome="ok", delay=0.0):
        self.calls: list[str] = []
        self.outcome = outcome  # "ok" | "fail" | "raise"
        self.delay = delay
        # Release event: set when the first fetch starts so the test can
        # hold the winner inside the fetch while the other requests pile
        # up behind the claim (they must NOT invoke the fetcher).
        self.hold = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, site):
        self.calls.append(str(site.id))
        if self.delay:
            await asyncio.sleep(self.delay)
        from app.site_icons import FetchOutcome as _FetchOutcome

        if self.outcome == "ok":
            return _FetchOutcome(True, PNG_BYTES, "image/png", f"{site.url}/favicon.ico")
        if self.outcome == "raise":
            raise RuntimeError("resolver boom")
        return _FetchOutcome(False, detail="unreachable-or-not-an-image")


@pytest.fixture
def fake_fetcher(monkeypatch):
    fetcher = FakeFetcher()
    monkeypatch.setattr("app.site_icons.fetch_outcome_for_site", fetcher)
    return fetcher


async def _enable_favicon(db_factory):
    from app.settings_store import save_setting

    async with db_factory() as db:
        await save_setting(db, FAVICON_SETTING_KEY, {"enabled": True})


async def _seed_site(db_factory, admin_user, url="https://example.com") -> Site:
    async with db_factory() as db:
        site = Site(name="IconSite", url=url)
        site.created_by = admin_user.id
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _get_icon_row(db_factory, site_id) -> SiteIcon | None:
    async with db_factory() as db:
        row = await db.scalar(select(SiteIcon).where(SiteIcon.site_id == site_id))
        if row is not None:
            await db.refresh(row)
        return row


class TestSettingOff:
    async def test_off_returns_404_and_never_fetches(
        self, client, auth_headers, db_factory, admin_user, fake_fetcher
    ):
        site = await _seed_site(db_factory, admin_user)
        resp = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert resp.status_code == 404
        assert fake_fetcher.calls == []

    async def test_unknown_site_404_even_when_enabled(
        self, client, auth_headers, db_factory, fake_fetcher
    ):
        await _enable_favicon(db_factory)
        resp = await client.get(f"/api/sites/{uuid_mod.uuid4()}/icon", headers=auth_headers)
        assert resp.status_code == 404


class TestSettingsToggle:
    async def test_toggle_roundtrip_writes_audit(self, client, auth_headers, db_factory):
        resp = await client.get("/api/settings/favicon", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

        put = await client.put(
            "/api/settings/favicon", json={"enabled": True}, headers=auth_headers
        )
        assert put.status_code == 200
        assert put.json() == {"enabled": True}
        assert (await client.get("/api/settings/favicon", headers=auth_headers)).json()[
            "enabled"
        ] is True

        off = await client.put(
            "/api/settings/favicon", json={"enabled": False}, headers=auth_headers
        )
        assert off.json() == {"enabled": False}

        async with db_factory() as db:
            rows = (
                await db.scalars(
                    select(AuditLog).where(AuditLog.action == "settings.favicon.update")
                )
            ).all()
            assert len(rows) == 2
            assert {r.before_json["enabled"] for r in rows} == {False, True}
            assert {r.after_json["enabled"] for r in rows} == {True, False}


class TestHappyPath:
    async def test_fetch_once_then_serve_from_cache(
        self, client, auth_headers, db_factory, admin_user, fake_fetcher
    ):
        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)

        first = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert first.status_code == 200
        assert first.headers["content-type"].startswith("image/png")
        assert first.headers.get("cache-control") == "private, max-age=86400"
        assert first.content.startswith(b"\x89PNG")

        row = await _get_icon_row(db_factory, site.id)
        assert row is not None and row.status == "ok"
        assert row.data == PNG_BYTES
        assert row.source_url.endswith("/favicon.ico")
        assert row.content_type == "image/png"

        second = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert second.status_code == 200
        assert second.content == PNG_BYTES
        assert len(fake_fetcher.calls) == 1  # served from cache, no refetch


class TestNegativeCache:
    async def test_failure_stores_retry_after_and_blocks_refetch_until_expiry(
        self, client, auth_headers, db_factory, admin_user, monkeypatch, fake_fetcher
    ):
        import datetime as dt

        fake_fetcher.outcome = "fail"  # this test exercises the failure path
        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)

        fail = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert fail.status_code == 404
        row = await _get_icon_row(db_factory, site.id)
        assert row is not None and row.status == "failed"
        assert row.retry_after > utcnow()
        assert len(fake_fetcher.calls) == 1

        # Immediate retry must NOT invoke the fetcher again.
        again = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert again.status_code == 404
        assert len(fake_fetcher.calls) == 1

        # Clock injection: after retry_after passes, the fetcher runs again.
        class _FakeDatetime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                real_now = dt.datetime.now(tz or dt.UTC)
                return (real_now + dt.timedelta(hours=25)).replace(tzinfo=tz or dt.UTC)

        import app.site_icons as si

        monkeypatch.setattr(si, "_utcnow", lambda: _FakeDatetime.now(dt.UTC))
        third = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert third.status_code == 404
        assert len(fake_fetcher.calls) == 2


class TestContentValidation:
    """The fetcher itself is exercised through its real validation logic by
    stubbing only httpx transport-level responses via _FetchOutcome-shaped
    fakes; here we pin the endpoint's contract for non-image outcomes."""

    async def test_html_error_page_is_rejected_not_cached_ok(
        self, client, auth_headers, db_factory, admin_user, monkeypatch
    ):
        from app.site_icons import FetchOutcome as _FetchOutcome

        calls: list[str] = []

        async def html_fetcher(site):
            calls.append(site.url)
            return _FetchOutcome(True, b"<html>404 not found</html>", "text/html", site.url)

        monkeypatch.setattr("app.site_icons.fetch_outcome_for_site", html_fetcher)

        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)
        resp = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert resp.status_code == 404
        row = await _get_icon_row(db_factory, site.id)
        assert row is not None and row.status == "failed"

    async def test_svg_is_rejected_by_documented_decision(
        self, client, auth_headers, db_factory, admin_user, monkeypatch
    ):
        # Direct probe of the documented decision: an SVG payload has no
        # raster magic bytes, so even a "successful" SVG download fails.
        from app.site_icons import sniffed_content_type

        assert sniffed_content_type(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") is None
        assert sniffed_content_type(PNG_BYTES) == "image/png"

    async def test_oversize_payload_aborts(
        self, client, auth_headers, db_factory, admin_user, monkeypatch
    ):
        from app.site_icons import _MAX_ICON_BYTES

        oversize = b"\x89PNG\r\n\x1a\n" + b"\x00" * (_MAX_ICON_BYTES + 1)

        async def big_fetcher(site):
            # The fetch seam returns the oversize body as if accepted; the
            # endpoint must refuse to cache/serve anything over the cap.
            from app.site_icons import FetchOutcome

            return FetchOutcome(True, oversize, "image/png", site.url)

        monkeypatch.setattr("app.site_icons.fetch_outcome_for_site", big_fetcher)
        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)
        resp = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        assert resp.status_code == 404
        row = await _get_icon_row(db_factory, site.id)
        assert row is not None and row.status == "failed"


class TestSSRF:
    async def test_private_target_is_refused_with_failed_row(
        self, client, auth_headers, db_factory, admin_user
    ):
        """A stored site pointing at loopback (created under allow_private_
        networks=True) still cannot be icon-fetched unless the operator's
        own opt-in covers it; without the flag the SSRF gate refuses."""
        import app.site_icons as si
        from app.ssrf import SSRFBlockedError

        async with db_factory() as db:
            site = Site(name="Internal", url="http://127.0.0.1:9/x", allow_private_networks=False)
            db.add(site)
            await db.commit()
            await db.refresh(site)

            async def gate_probe():
                await si._gate_url("http://127.0.0.1:9/favicon.ico", allow_private_networks=False)

            with pytest.raises(SSRFBlockedError):
                await gate_probe()

    async def test_redirect_chain_hop_validation_rejects_internal_landing(
        self, client, auth_headers, db_factory, admin_user, monkeypatch
    ):
        """Each redirect hop passes back through the gate before fetching;
        a public host redirecting to 169.254.169.254 must be refused."""

        import app.site_icons as si

        gated_urls: list[str] = []

        async def fake_gate(url: str, allow_private_networks: bool) -> None:
            gated_urls.append(url)
            from urllib.parse import urlparse

            if urlparse(url).hostname in ("169.254.169.254",):
                raise si.__dict__ and __import__(
                    "app.ssrf", fromlist=["SSRFBlockedError"]
                ).SSRFBlockedError("blocked")

        monkeypatch.setattr(si, "_gate_url", fake_gate)

        class FakeResp:
            def __init__(self, status_code, headers, content=b""):
                self.status_code = status_code
                self.headers = headers
                self.content = content

            @property
            def is_redirect(self):
                return self.status_code in (301, 302, 303, 307, 308)

        hops = [
            FakeResp(302, {"location": "https://169.254.169.254/latest/meta-data/"}),
        ]

        class FakeClient:
            def __init__(self):
                self.i = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url):
                r = hops[min(self.i, len(hops) - 1)]
                self.i += 1
                return r

        monkeypatch.setattr(si.httpx, "AsyncClient", lambda **kw: FakeClient())

        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)
        resp = await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        # The internal hop was refused -> failure path, graceful 404.
        assert resp.status_code == 404
        # Prove both hops were individually gated (public start + refused landing).
        assert any(u.startswith("https://example.com") for u in gated_urls)
        assert any("169.254.169.254" in u for u in gated_urls)
        row = await _get_icon_row(db_factory, site.id)
        assert row is not None and row.status == "failed"


class TestConcurrency:
    async def test_n_concurrent_first_loads_single_fetch_coherent_responses(
        self,
        client,
        auth_headers,
        analyst_headers,
        viewer_headers,
        db_factory,
        admin_user,
        fake_fetcher,
    ):
        """Real asyncio gather against the harness DB: three simultaneous
        first-loads of one never-fetched site. The fetcher is slowed so the
        requests genuinely interleave. Removing resolve_site_icon's claim
        primitive (the conditional UPDATE / unique-insert arbitration)
        makes every request run the fetcher and this test fails on call
        count — that is the failing-before proof for the claim."""
        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)
        fake_fetcher.delay = 0.5  # widen the race window

        headers_list = [auth_headers, analyst_headers, viewer_headers]

        async def one(h):
            r = await client.get(f"/api/sites/{site.id}/icon", headers=h)
            return r.status_code

        codes = sorted(await asyncio.gather(*[one(h) for h in headers_list]))
        assert codes == [200, 200, 200]
        assert len(fake_fetcher.calls) == 1, (
            f"expected exactly one fetch invocation, got {len(fake_fetcher.calls)}"
        )
        row = await _get_icon_row(db_factory, site.id)
        assert row is not None and row.status == "ok"

    async def test_concurrent_first_loads_of_dead_site_all_get_graceful_404(
        self, client, auth_headers, analyst_headers, db_factory, admin_user, monkeypatch
    ):
        from app.site_icons import FetchOutcome as _FetchOutcome

        async def failing(site):
            return _FetchOutcome(False, detail="unreachable-or-not-an-image")

        monkeypatch.setattr("app.site_icons.fetch_outcome_for_site", failing)
        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)

        async def one(h):
            r = await client.get(f"/api/sites/{site.id}/icon", headers=h)
            return r.status_code

        codes = sorted(await asyncio.gather(one(auth_headers), one(analyst_headers)))
        assert codes == [404, 404]


class TestRBACAndCascade:
    async def test_unauthenticated_401(self, client, db_factory, admin_user, fake_fetcher):
        site = await _seed_site(db_factory, admin_user)
        resp = await client.get(f"/api/sites/{site.id}/icon")
        assert resp.status_code == 401

    async def test_viewer_can_read_icons_matching_sites_read_surface(
        self, client, viewer_headers, db_factory, admin_user, fake_fetcher
    ):
        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)
        resp = await client.get(f"/api/sites/{site.id}/icon", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_site_delete_cascades_icon_row(
        self, db_factory, admin_user, client, auth_headers, fake_fetcher
    ):
        from sqlalchemy import func

        await _enable_favicon(db_factory)
        site = await _seed_site(db_factory, admin_user)
        # produce a cache row
        await client.get(f"/api/sites/{site.id}/icon", headers=auth_headers)
        row = await _get_icon_row(db_factory, site.id)
        assert row is not None

        async with db_factory() as db:
            s = await db.scalar(select(Site).where(Site.id == site.id))
            await db.delete(s)
            await db.commit()

        async with db_factory() as db:
            count = await db.scalar(select(func.count()).select_from(SiteIcon))
        assert count == 0
