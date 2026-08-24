"""Phase 35 — Low sweep, backend correctness.

Four findings, one module:

- NaN/Infinity in any float field returned 500 instead of 422 (the
  validation-error response embedded the non-JSON-compliant input and
  Starlette's allow_nan=False rendering crashed). Fixed by a strict-JSON
  middleware that rejects the constants before pydantic ever sees them.
  Phase-35 addition beyond the filed evidence: overflow literals such as
  `1e400` are VALID JSON text that parses to inf and crashed the same way,
  so the middleware rejects any non-finite number, not just the spelled-out
  constants.
- Whitespace-only names passed PATCH validation on notification channels
  and remediation hooks (min_length ran on the raw input; the router then
  stripped to ""). Fixed with strip-and-reject validators on both Update
  models.
- Duplicate `acting_user_email` declaration in TelegramSettingsOut.
- Worker called DNS-resolving assert_url_allowed synchronously inside
  async functions (fetcher.py x2, probe.py x2). Fixed via asyncio.to_thread,
  matching fetcher's own route-guard precedent.
"""

import inspect
import json

import httpx
import pytest

from app.main import _reject_constant
from app.schemas import NotificationChannelUpdate, RemediationHookUpdate, TelegramSettingsOut
from tests.conftest import TEST_PASSWORD

# ---------------------------------------------------------------------------
# Finding: NaN/Infinity in any float field returns 500 instead of 422
# ---------------------------------------------------------------------------


async def _login(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _raw_body(template_tail: str) -> bytes:
    return ('{"name": "NaN Probe", "url": "http://127.0.0.1/nan-probe", ' + template_tail).encode()


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
async def test_non_finite_json_constants_get_422_not_500(
    client: httpx.AsyncClient, admin_user, literal: str
) -> None:
    """The audit's exact probe shape: a raw body with a non-finite constant
    against POST /api/sites (SiteCreate.flag_threshold). Pre-fix each returned
    500 (Starlette crashed serializing pydantic's error response); post-fix
    the strict parser rejects the body as malformed JSON with 422."""
    headers = await _login(client, admin_user.email)
    raw = _raw_body(f'"flag_threshold": {literal}}}')

    resp = await client.post(
        "/api/sites", content=raw, headers={"Content-Type": "application/json", **headers}
    )
    assert resp.status_code == 422, resp.text
    assert "not valid JSON" in resp.json()["detail"]
    # And nothing was created.
    listing = await client.get("/api/sites", headers=headers)
    assert all(s["url"] != "http://127.0.0.1/nan-probe" for s in listing.json())


async def test_overflow_literal_1e400_also_422_not_500(
    client: httpx.AsyncClient, admin_user
) -> None:
    """`1e400` is VALID JSON text — parse_constant never fires — but it
    parses to inf, pydantic's le=1.0 then rejects it, and pre-fix the same
    serialization crash produced a 500. The middleware's finite check closes
    this sibling path."""
    headers = await _login(client, admin_user.email)
    raw = _raw_body('"flag_threshold": 1e400}')

    resp = await client.post(
        "/api/sites", content=raw, headers={"Content-Type": "application/json", **headers}
    )
    assert resp.status_code == 422, resp.text


async def test_patch_flag_threshold_nan_gets_422_not_500(
    client: httpx.AsyncClient, auth_headers, db_factory
) -> None:
    """SiteUpdate.flag_threshold was the audit's second named surface."""
    from app.models import Site

    async with db_factory() as db:
        site = Site(name="Nan Patch", url="http://127.0.0.1/nan-patch")
        db.add(site)
        await db.commit()
        site_id = site.id

    resp = await client.request(
        "PATCH",
        f"/api/sites/{site_id}",
        content=b'{"flag_threshold": NaN}',
        headers={"Content-Type": "application/json", **auth_headers},
    )
    assert resp.status_code == 422


async def test_valid_json_still_parses_normally(client, auth_headers, stub_all_enqueues) -> None:
    """Behavior-preservation guard: ordinary JSON (including floats that are
    merely extreme-but-finite) flows through unchanged."""
    resp = await client.post(
        "/api/sites",
        json={
            "name": "Finite",
            "url": "http://127.0.0.1/finite",
            "flag_threshold": 1e-9,
            "allow_private_networks": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["flag_threshold"] == pytest.approx(1e-9)


async def test_malformed_json_is_422_with_clean_detail(client, auth_headers) -> None:
    """Ordinary garbage is still rejected — now with a stable detail string."""
    resp = await client.post(
        "/api/sites",
        content=b"{not json at all",
        headers={"Content-Type": "application/json", **auth_headers},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Request body is not valid JSON"


async def test_non_json_content_type_bypasses_the_strict_parser(client, auth_headers) -> None:
    """The middleware only guards application/json bodies; other content
    types keep their existing semantics (here: FastAPI's own rejection for a
    body it cannot parse as JSON) — no new verdict invented for them."""
    resp = await client.post(
        "/api/sites",
        content=b'{"name": "x", "url": "http://127.0.0.1/x"}',
        headers={"Content-Type": "text/plain", **auth_headers},
    )
    # Whatever FastAPI does with a text/plain body on a JSON endpoint, it
    # must NOT be our middleware detail (proving scope containment).
    if resp.status_code == 422:
        assert resp.json()["detail"] != "Request body is not valid JSON"


def test_strict_parser_rejects_constants_and_overflows_at_unit_level() -> None:
    """Direct unit proof of the mechanism: parse_constant fires exactly for
    the three Python-lenient constants; the finite check catches overflowed
    floats nested anywhere in a payload; valid payloads pass untouched."""
    from app.main import _ensure_finite

    for literal in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError):
            json.loads(f'{{"x": {literal}}}', parse_constant=_reject_constant)

    with pytest.raises(ValueError):
        _ensure_finite({"flag_threshold": json.loads("1e400")})
    with pytest.raises(ValueError):
        _ensure_finite({"nested": [{"deep": [float("nan")]}]})
    # Valid data is untouched.
    _ensure_finite({"ok": [1.5, 2, {"tiny": 1e-300}, None, True, "s"]})


# ---------------------------------------------------------------------------
# Finding: Whitespace-only names pass PATCH validation
# ---------------------------------------------------------------------------


class TestWhitespaceOnlyPatchNames:
    @pytest.mark.parametrize("bad", ["   ", "\t\n ", "\u00a0\u00a0"])
    async def test_channel_patch_whitespace_name_rejected_422(
        self, client, auth_headers, bad: str
    ) -> None:
        create = await client.post(
            "/api/notification-channels",
            json={"type": "email", "name": "Ops Email", "to": "ops@example.com"},
            headers=auth_headers,
        )
        assert create.status_code == 201, create.text
        channel = create.json()

        resp = await client.patch(
            f"/api/notification-channels/{channel['id']}",
            json={"name": bad},
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text

        # The stored name is untouched by the refused PATCH.
        after = await client.get("/api/notification-channels", headers=auth_headers)
        kept = next(c for c in after.json() if c["id"] == channel["id"])
        assert kept["name"] == "Ops Email"

    @pytest.mark.parametrize("bad", ["   ", "\t\n "])
    async def test_hook_patch_whitespace_name_rejected_422(
        self, client, auth_headers, admin_user, db_factory, bad: str
    ) -> None:
        from app.models import Site

        async with db_factory() as db:
            site = Site(name="Hook WS", url="http://127.0.0.1/hook-ws")
            db.add(site)
            await db.commit()
            site_id = site.id

        create = await client.post(
            f"/api/sites/{site_id}/remediation-hooks",
            json={
                "name": "Restore Page",
                "action_type": "custom_webhook",
                "webhook_url": "http://127.0.0.1:1/restore",
                "allow_private_networks": True,
            },
            headers=auth_headers,
        )
        assert create.status_code == 201, create.text
        hook = create.json()

        resp = await client.patch(
            f"/api/sites/{site_id}/remediation-hooks/{hook['id']}",
            json={"name": bad},
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text

        listed = await client.get(f"/api/sites/{site_id}/remediation-hooks", headers=auth_headers)
        kept = next(h for h in listed.json() if h["id"] == hook["id"])
        assert kept["name"] == "Restore Page"

    def test_update_schema_units_strip_then_reject(self) -> None:
        """Schema-level contract: real names come back STRIPPED (so the router
        stores what the schema validated), whitespace-only rejects, absent
        name stays absent (PATCH optionality preserved)."""
        assert NotificationChannelUpdate(name="  Padded Name  ").name == "Padded Name"
        assert RemediationHookUpdate(name="  Hook Name ").name == "Hook Name"

        import pydantic

        with pytest.raises(pydantic.ValidationError):
            NotificationChannelUpdate(name="   ")
        with pytest.raises(pydantic.ValidationError):
            RemediationHookUpdate(name="\t")

        assert NotificationChannelUpdate().name is None
        assert RemediationHookUpdate().name is None

    async def test_channel_create_whitespace_name_also_rejected(self, client, auth_headers) -> None:
        """Create paths already defended this invariant — guard that they
        still do alongside the repaired PATCH paths."""
        resp = await client.post(
            "/api/notification-channels",
            json={"type": "email", "name": "   ", "to": "ops@example.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Finding: Duplicate field definition acting_user_email in TelegramSettingsOut
# ---------------------------------------------------------------------------


def test_telegram_settings_out_declares_acting_user_email_once() -> None:
    """The merge artifact declared acting_user_email twice back-to-back;
    pydantic silently kept one. Pin the deduplicated source AND its runtime
    shape/default so divergence cannot return silently."""
    text = inspect.getsource(TelegramSettingsOut)
    occurrences = [ln for ln in text.splitlines() if "acting_user_email" in ln]
    assert len(occurrences) == 1, occurrences

    fields = TelegramSettingsOut.model_fields
    assert "acting_user_email" in fields
    assert fields["acting_user_email"].default is None

    out = TelegramSettingsOut(configured=False)
    assert out.acting_user_email is None


# ---------------------------------------------------------------------------
# Finding: sync DNS-resolving assert_url_allowed inside async worker code
# ---------------------------------------------------------------------------


class TestWorkerChecksOffloaded:
    """All four direct-in-async call sites now route through
    asyncio.to_thread, pinned behaviorally by spying on each module's
    to_thread reference (the modules resolve it off their own `asyncio`
    attribute at call time, exactly like fetcher's existing route guard)."""

    @staticmethod
    async def _spy_to_thread(calls: list, fn, *args, **kwargs):
        calls.append((fn.__module__, getattr(fn, "__qualname__", fn)))
        return fn(*args, **kwargs)

    async def test_probe_site_top_level_check_offloaded(self, monkeypatch) -> None:
        """probe_site's entry check must not resolve DNS on the loop; a
        refusal still short-circuits into the degrade-to-empty result."""
        import worker.probe as probe_mod

        calls: list = []

        async def spy(fn, *a, **kw):
            return await self._spy_to_thread(calls, fn, *a, **kw)

        monkeypatch.setattr(probe_mod.asyncio, "to_thread", spy)

        result = await probe_mod.probe_site("http://169.254.169.254/nope")
        assert result.tls is None  # probe_site never raises; degrades
        assert any(m.endswith("ssrf") for m, _ in calls), calls

    async def test_probe_site_blocked_url_records_no_check_on_loop(self, monkeypatch) -> None:
        """A refused URL still produces exactly one offloaded check whose
        SSRFBlockedError lands in the warning path (behavior unchanged,
        now threaded)."""
        import logging

        import worker.probe as probe_mod

        calls: list = []
        warnings: list[str] = []

        async def spy(fn, *a, **kw):
            return await self._spy_to_thread(calls, fn, *a, **kw)

        monkeypatch.setattr(probe_mod.asyncio, "to_thread", spy)
        monkeypatch.setattr(
            probe_mod.logger,
            "warning",
            lambda msg, *a: warnings.append(msg % a if a else msg),
        )

        result = await probe_mod.probe_site("http://10.255.255.1/internal")
        assert result.tls is None
        assert len(calls) == 1 and calls[0][0].endswith("ssrf"), calls
        assert any("blocked" in w.lower() for w in warnings), warnings
        del logging  # imported only to document the log-path intent

    async def test_redirect_guard_routes_check_through_a_thread(self, monkeypatch) -> None:
        """The _redirect_guard hook offloads its hop re-validation."""
        import worker.probe as probe_mod

        calls: list = []

        async def spy(fn, *a, **kw):
            return await self._spy_to_thread(calls, fn, *a, **kw)

        monkeypatch.setattr(probe_mod.asyncio, "to_thread", spy)

        guard = probe_mod._redirect_guard(allow_private_networks=False)
        response = type("R", (), {})()
        response.next_request = httpx.Request("GET", "http://example.com/redirected-target")

        await guard(response)  # must not raise for a global host
        assert any(m.endswith("ssrf") for m, _ in calls), calls

    async def test_redirect_guard_passes_ssrf_refusal_through(self, monkeypatch) -> None:
        """A blocked redirect hop still raises SSRFBlockedError (the caller
        records it into variant.error) — threading must not change policy."""
        import worker.probe as probe_mod
        from app.ssrf import SSRFBlockedError

        async def immediate(fn, *a, **kw):
            return fn(*a, **kw)

        monkeypatch.setattr(probe_mod.asyncio, "to_thread", immediate)
        monkeypatch.setattr(
            probe_mod,
            "assert_url_allowed",
            lambda url, **kw: (_ for _ in ()).throw(SSRFBlockedError("blocked hop")),
        )

        guard = probe_mod._redirect_guard(allow_private_networks=False)
        response = type("R", (), {})()
        response.next_request = httpx.Request("GET", "http://169.254.169.254/latest")

        with pytest.raises(SSRFBlockedError):
            await guard(response)

    async def test_fetch_page_both_checks_offloaded(self, monkeypatch) -> None:
        """Both direct checks inside fetch_page run via `await
        asyncio.to_thread(...)` — pinned at the seam level plus behavioral
        proof that a refusal raises before Playwright ever launches."""
        import worker.fetcher as fetcher_mod

        src = inspect.getsource(fetcher_mod.fetch_page)
        assert src.count("await asyncio.to_thread(") >= 2, src

        calls: list = []

        real_assert = fetcher_mod.assert_url_allowed

        def refusing_assert(url, **kwargs):
            # Records through the spy's closure list via to_thread below.
            raise _refusal(url)

        from app.ssrf import SSRFBlockedError

        def _refusal(url):
            return SSRFBlockedError(f"refused: {url}")

        async def spy(fn, *a, **kw):
            calls.append((fn.__module__, getattr(fn, "__name__", "?")))
            try:
                return fn(*a, **kw)
            except SSRFBlockedError:
                raise

        monkeypatch.setattr(fetcher_mod.asyncio, "to_thread", spy)
        monkeypatch.setattr(fetcher_mod, "assert_url_allowed", refusing_assert)

        launched = False

        class FakePW:
            def __call__(self):
                nonlocal launched
                launched = True
                raise AssertionError("Playwright must not launch when the URL is refused")

        monkeypatch.setattr(fetcher_mod, "async_playwright", FakePW())

        with pytest.raises(SSRFBlockedError):
            await fetcher_mod.fetch_page("http://example.com/refused")
        assert launched is False
        # The refusal traveled THROUGH the offload seam: fetch_page passed
        # its (patched) check callable into to_thread, so the spy saw exactly
        # one threaded execution before the raise. If fetch_page ever regresses
        # to calling assert_url_allowed directly, `calls` comes back empty.
        assert len(calls) == 1 and calls[0][1] == "refusing_assert", calls
        del real_assert
