"""Phase 16: outbound-fetch / SSRF-adjacent fixes.

Finding A (ssrf.py): the relaxed ``allow_private_networks`` policy refused
globally-routed addresses the DEFAULT policy accepts, because Python reports
some IANA special-purpose ranges as BOTH ``is_global`` and ``is_reserved``
(RFC 6052 NAT64 ``64:ff9b::/96``, SRV ``5f00::/16``) — opting in was stricter
than not, breaking AI provider setup on DNS64/NAT64 networks.

Finding B (settings router): ``POST /api/settings/ai/ollama/pull`` fetched any
unvalidated ``base_url``, silently degraded bad ``provider_id``\\ s into
raw-URL fetches, and had no explicit per-user rate limit; the sibling
list-models endpoint fetched stored base URLs without revalidation.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.ssrf import SSRFBlockedError, _address_blocked, assert_url_allowed


def _addr(s: str):
    import ipaddress

    return ipaddress.ip_address(s)


# --- Finding A: relaxed-policy superset invariant -------------------------


class TestRelaxedPolicySupersetInvariant:
    def test_nat64_wellknown_allowed_by_default(self) -> None:
        # Guard: the default policy always allowed NAT64 (is_global=True).
        assert_url_allowed("http://[64:ff9b::2224:850f]/")

    @pytest.mark.parametrize(
        "literal",
        [
            "64:ff9b::",  # prefix low boundary
            "64:ff9b::ffff:ffff",  # prefix high boundary
            "64:ff9b::2224:850f",  # the audit's own synthesized address
        ],
    )
    def test_nat64_wellknown_allowed_with_optin(self, literal: str) -> None:
        # FAILED pre-fix: relaxed policy blocked these (is_reserved=True).
        assert_url_allowed(f"http://[{literal}]/", allow_private_networks=True)

    def test_srv_range_global_reserved_allowed_with_optin(self) -> None:
        # Same inversion class discovered by the Phase 16 sweep (5f00::/16).
        assert_url_allowed("http://[5f00::1]/", allow_private_networks=True)

    @pytest.mark.parametrize(
        "address",
        [
            "64:ff9b::8000:1",
            "5f00::abcd",
            "2620:0:2d0:200::7",  # plain global unicast control
        ],
    )
    def test_relaxed_never_stricter_than_default(self, address: str) -> None:
        # Property sweep over the inversion class: anything the default
        # policy accepts must also be accepted under the opt-in.
        addr = _addr(address)
        assert _address_blocked(addr, False) is False
        assert _address_blocked(addr, True) is False

    def test_shared_helper_flows_to_pinning_transport(self) -> None:
        # ssrf_transport.SSRFPinningTransport imports _address_blocked, so the
        # policy fix applies to the pinning transport automatically; pin the
        # shared symbol's behavior explicitly here.
        assert _address_blocked(_addr("64:ff9b::1"), True) is False
        assert _address_blocked(_addr("64:ff9b::7f00:1"), False) is False

    def test_localuse_nat64_stays_blocked_in_both_policies(self) -> None:
        # RFC 8215 local-use NAT64 (64:ff9b:1::/48) is NOT globally routed
        # (is_global=False): both policies refuse it — no inconsistency.
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed("http://[64:ff9b:1::1]/")
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed("http://[64:ff9b:1::1]/", allow_private_networks=True)


class TestRelaxedPolicyGuardsUnchanged:
    @pytest.mark.parametrize(
        "url",
        [
            "http://[ff02::1]/",  # multicast
            "http://[::]/",  # unspecified
            "http://240.0.0.1/",  # reserved IPv4
            "http://100::1/",  # discard-only range
        ],
    )
    def test_still_blocked_even_with_optin(self, url: str) -> None:
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed(url, allow_private_networks=True)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://[::1]/",
            "http://192.168.1.1/",
            "http://100.64.0.1/",
            "http://[fe80::1]/",
            "http://[fd00::1]/",
        ],
    )
    def test_hostable_ranges_still_need_optin(self, url: str) -> None:
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed(url)
        assert_url_allowed(url, allow_private_networks=True)

    def test_optin_refusal_message_does_not_suggest_enabling_the_flag(self) -> None:
        # FAILED pre-fix: refusals under the opt-in told users to enable the
        # flag they had already enabled.
        with pytest.raises(SSRFBlockedError) as excinfo:
            assert_url_allowed("http://240.0.0.1/", allow_private_networks=True)
        assert "allow private networks" not in str(excinfo.value)

    def test_default_refusal_message_keeps_the_hint(self) -> None:
        with pytest.raises(SSRFBlockedError) as excinfo:
            assert_url_allowed("http://240.0.0.1/")
        assert "allow private networks" in str(excinfo.value)


async def test_validate_base_url_accepts_nat64_for_local_provider_types() -> None:
    # The availability bug's exact shape: configuring an ollama provider
    # whose host resolves through DNS64 failed with ProviderConfigError.
    from app.ai_config import validate_base_url

    await validate_base_url("http://[64:ff9b::2224:850f]:11434", "ollama")


# --- Finding B: ollama pull / list-models outbound discipline -------------


class _CanaryState(dict):
    hits: list


def _canary_handler(state: _CanaryState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            state["hits"].append(
                {
                    "method": self.command,
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            payload = json.dumps({"status": "pulling manifest", "digest": "p16-canary"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            pass

    return Handler


@pytest.fixture()
async def pull_canary():
    state: _CanaryState = _CanaryState(hits=[])
    server = ThreadingHTTPServer(("127.0.0.1", 0), _canary_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"url": f"http://127.0.0.1:{server.server_address[1]}", "hits": state["hits"]}
    finally:
        server.shutdown()
        server.server_close()


def _stub_pull_stream(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Replace ai_ollama.pull_stream (imported locally by the endpoint) with a
    deterministic generator; returns the call log."""
    import app.ai_ollama as ai_ollama

    calls: list[dict] = []

    async def fake_stream(base_url, model, api_key=None):
        calls.append({"base_url": base_url, "model": model, "api_key": api_key})
        yield {"status": "stub-progress"}

    monkeypatch.setattr(ai_ollama, "pull_stream", fake_stream)
    return calls


class TestOllamaPullProviderResolution:
    async def test_unknown_provider_id_surfaces_404_and_fetches_nothing(
        self, client, auth_headers, pull_canary
    ):
        # FAILED pre-fix: 200 + live fetch of the raw base_url instead of 404.
        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"provider_id": "not-a-uuid", "base_url": pull_canary["url"], "model": "m"},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert pull_canary["hits"] == []

    async def test_malformed_uuid_provider_id_also_404s(self, client, auth_headers):
        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"provider_id": "%00", "model": "m"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_non_ollama_provider_returns_400_not_silent_fallback(
        self, client, auth_headers, db_factory, pull_canary
    ):
        from sqlalchemy import select

        from app.ai_config import create_provider
        from app.models import AiProvider

        async with db_factory() as db:
            await create_provider(
                db,
                label="hosted",
                provider_type="google",
                api_keys=["k"],
                base_url=None,
            )
            await db.commit()
            pid = str((await db.scalars(select(AiProvider.id))).first())

        # FAILED pre-fix: fell through to pulling from the default target.
        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"provider_id": pid, "base_url": pull_canary["url"], "model": "m"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "Not an Ollama provider" in resp.json()["detail"]
        assert pull_canary["hits"] == []


class TestOllamaPullUrlValidation:
    async def test_rejects_non_http_scheme_before_any_request(
        self, client, auth_headers, pull_canary
    ):
        # FAILED pre-fix: 200 SSE stream (the scheme error surfaced only as a
        # streamed event after the fetch attempt).
        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"base_url": "file:///etc/passwd", "model": "m"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "http" in resp.json()["detail"].lower()

    async def test_validates_the_effective_normalized_target(
        self, client, auth_headers, monkeypatch
    ):
        from app.routers import settings as settings_router

        seen: list[tuple] = []

        async def spy_validate(url: str, provider_type: str) -> None:
            seen.append((url, provider_type))

        monkeypatch.setattr(settings_router, "validate_base_url", spy_validate)
        _stub_pull_stream(monkeypatch)

        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"base_url": "http://127.0.0.1:9/v1/", "model": "m"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # FAILED pre-fix: no validation ran at all. Post-fix the URL that is
        # actually fetched (normalized, /v1 stripped) is what gets validated.
        assert seen == [("http://127.0.0.1:9", "ollama")]

    async def test_loopback_canary_flow_still_works_end_to_end(
        self, client, auth_headers, pull_canary
    ):
        # Behavior-preservation guard (passes pre+post): the legitimate
        # local-download flow streams progress reflected from the daemon.
        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"base_url": pull_canary["url"], "model": "canary-model"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = (await resp.aread()).decode()
        assert "p16-canary" in body
        assert '"status": "success"' in body.replace(", ", ", ")
        assert len(pull_canary["hits"]) == 1
        hit = pull_canary["hits"][0]
        assert hit["path"] == "/api/pull"
        assert json.loads(hit["body"])["model"] == "canary-model"

    async def test_provider_flow_uses_stored_url_and_key(
        self, client, auth_headers, db_factory, pull_canary
    ):
        from sqlalchemy import select

        from app.ai_config import create_provider
        from app.models import AiProvider

        async with db_factory() as db:
            provider = await create_provider(
                db,
                label="local daemon",
                provider_type="ollama",
                api_keys=["daemon-key"],
                base_url=pull_canary["url"],
            )
            await db.commit()
            pid = str(provider.id)
            _ = (
                await db.scalars(select(AiProvider.id))
            ).all()  # keep session warm; expire_on_commit=False

        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"provider_id": pid, "model": "stored-model"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(pull_canary["hits"]) == 1
        assert pull_canary["hits"][0]["authorization"] == "Bearer daemon-key"


class TestOllamaPullRateLimit:
    async def test_endpoint_enforces_user_rate_limit_explicitly(
        self, client, auth_headers, monkeypatch
    ):
        from app.routers import settings as settings_router

        calls: list[tuple] = []

        def spy_limit(request, user_id: str) -> None:
            calls.append((user_id,))

        monkeypatch.setattr(settings_router, "enforce_user_rate_limit", spy_limit)
        _stub_pull_stream(monkeypatch)

        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"base_url": "http://127.0.0.1:9", "model": "m"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # FAILED pre-fix: the endpoint itself never invoked the limiter (only
        # the generic auth dependency did).
        assert calls and calls[0][0]

    async def test_pull_draws_from_the_same_per_user_budget_as_validate(
        self, client, auth_headers, monkeypatch
    ):
        # Parity with the validate endpoint's documented rationale: the
        # explicit enforcement shares the auth dependency's bucket, so a
        # pull costs two tokens like a validate call does.
        from app.config import get_settings
        from app.ratelimit import reset_limiters

        get_settings.cache_clear()
        monkeypatch.setenv("RATE_LIMIT_PER_USER", "5")
        reset_limiters()
        try:
            _stub_pull_stream(monkeypatch)
            statuses = []
            for _ in range(3):
                resp = await client.post(
                    "/api/settings/ai/ollama/pull",
                    json={"base_url": "http://127.0.0.1:9", "model": "m"},
                    headers=auth_headers,
                )
                statuses.append(resp.status_code)
                await resp.aread()
            # Budget: login=1, then each pull costs 2 (auth + endpoint).
            # FAILED pre-fix: pulls cost one token, so all three returned 200.
            assert statuses[:2] == [200, 200]
            assert statuses[2] == 429
        finally:
            get_settings.cache_clear()
            monkeypatch.setenv("RATE_LIMIT_PER_USER", "0")
            reset_limiters()


class TestOllamaListModelsValidation:
    async def test_stored_base_url_validated_before_live_call(
        self, client, auth_headers, db_factory
    ):
        """A provider whose stored base_url would never pass validation (e.g.
        seeded by the legacy migration, which skips save-time checks) must be
        refused with 422 instead of attempted."""
        from uuid import UUID

        from app.models import AiProvider

        async with db_factory() as db:
            provider = AiProvider(
                label="legacy-seeded",
                provider_type="ollama",
                base_url="http://this-host-does-not-exist.invalid",
            )
            db.add(provider)
            await db.commit()
            provider_id = str(UUID(str(provider.id)))

        # FAILED pre-fix: the endpoint attempted the live /api/tags call and
        # surfaced a 502 after the connection failure.
        resp = await client.get(
            f"/api/settings/ai/providers/{provider_id}/ollama-models",
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestPullAuthSurface:
    async def test_analyst_cannot_pull(self, client, analyst_headers):
        resp = await client.post(
            "/api/settings/ai/ollama/pull",
            json={"base_url": "http://127.0.0.1:9", "model": "m"},
            headers=analyst_headers,
        )
        assert resp.status_code == 403
