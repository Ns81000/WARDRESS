"""PROMPT-003 Audit Phase 4E repro tests — AI provider integration + supply chain.

Each test pins one Phase 4E finding as CURRENT behavior (Rule 1: diagnosis
only — no production file was modified to make these pass):

- test_legacy_put_ollama_create_branch_stores_unvalidated_base_url: the
  deprecated ``PUT /api/settings/ollama`` *create* branch passes
  ``validate_url=False`` while the unified provider API refuses the identical
  URL — one writer of ``ai_providers.base_url`` skips the SSRF policy
  entirely (AUDIT-4E-1).
- test_validate_endpoint_never_consults_the_ssrf_policy /
  test_ollama_models_endpoint_does_consult_the_ssrf_policy /
  test_resolve_task_hands_unvalidated_base_url_to_litellm: use-time
  validation is applied to the two Ollama convenience endpoints and to
  neither the generic provider-validate endpoint nor the execution path
  detection's escalation actually calls (AUDIT-4E-1).
- test_router_configures_a_per_model_group_retry_budget /
  test_every_key_is_its_own_deployment_and_its_own_timeout /
  test_hung_deployment_degrades_after_one_timeout_budget: measured stall
  budget for a hung provider — one full 30 s timeout per deployment, and one
  deployment per API key, inside the scan's 420 s soft limit (AUDIT-4E-3).
- test_fetch_live_catalog_never_consults_the_ssrf_policy /
  test_fetch_live_catalog_builds_an_unpinned_client: the models.dev catalog
  fetch performs outbound I/O with no policy check and no pinning transport
  (AUDIT-4E-2).
- test_normalize_base_falls_back_to_the_docker_hostname: the module comment
  claims the bare-host default is localhost, but None/"" resolve to the
  Docker service hostname and only whitespace-only input reaches localhost
  (AUDIT-4E-6).
- test_ollama_pull_client_has_no_deadline: the /api/pull stream is built
  with ``timeout=None`` (AUDIT-4E-7).
- test_scrub_only_catches_prefix_or_length_shaped_secrets: log redaction
  misses short custom-endpoint keys, which provider errors echo verbatim
  (AUDIT-4E-8).
- test_every_ai_provider_write_path_stores_fernet_ciphertext: positive
  verification that both credential write paths encrypt, that the redacted
  provider view never leaks the secret, and that a key rotation replaces the
  ciphertext (AUDIT-4E verified-clean ledger).
- test_torch_osv_gate_*: the torch advisory cross-check is wired into CI
  without a swallowing operator, is non-vacuous against the real lockfile,
  and actually fails (exit 1 advisory / exit 2 unverifiable) (AUDIT-4E
  supply-chain verification).
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import app.ai_catalog as ai_catalog
import app.ai_ollama as ai_ollama
import app.llm as llm
import app.ssrf as ssrf
from app.ai_config import ProviderConfigError, create_provider, update_provider, validate_base_url
from app.models import AiProvider, AiTaskAssignment, AiTaskType
from app.ssrf import SSRFBlockedError, assert_url_allowed

BACKEND_DIR = Path(__file__).resolve().parents[1]

# A URL the shared policy refuses for two independent reasons (non-http
# scheme, embedded credentials) and that resolves to nothing.
POLICY_REFUSED_URL = "ftp://user:secret@internal.invalid:21/v1"


def _load_tool(name: str):
    """Load a backend/tools script by path (tools/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location(name, BACKEND_DIR / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBaseUrlPolicyIsSkippedOnOneWriter:
    async def test_legacy_put_ollama_create_branch_stores_unvalidated_base_url(
        self, client, auth_headers
    ):
        """AUDIT-4E-1: the legacy create branch persists a base_url the policy
        refuses; the unified provider API refuses the identical input."""
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed("file:///etc/passwd")

        resp = await client.put(
            "/api/settings/ollama",
            json={"enabled": True, "base_url": "file:///etc/passwd", "model": "llama3.2"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["base_url"] == "file:///etc/passwd"

        # Same value through the non-deprecated writer: refused (422).
        unified = await client.post(
            "/api/settings/ai/providers",
            json={
                "label": "4e-unvalidated",
                "provider_type": "openai_compatible",
                "api_keys": [],
                "base_url": "file:///etc/passwd",
            },
            headers=auth_headers,
        )
        assert unified.status_code == 422

    async def test_validate_endpoint_never_consults_the_ssrf_policy(
        self, client, auth_headers, monkeypatch
    ):
        """AUDIT-4E-1: POST /providers/{id}/validate makes a live outbound call
        without consulting the SSRF policy (contrast: the Ollama endpoints do)."""
        import app.routers.settings as settings_router

        seen: list[str] = []
        real = settings_router.validate_base_url

        async def _spy(base_url, provider_type):
            seen.append(str(base_url))
            return await real(base_url, provider_type)

        monkeypatch.setattr(settings_router, "validate_base_url", _spy)

        created = await client.post(
            "/api/settings/ai/providers",
            json={
                "label": "4e-validate",
                "provider_type": "openai_compatible",
                "api_keys": [],
                # loopback: private networks are allowed for this provider type,
                # and nothing listens on port 9, so the call fails fast.
                "base_url": "http://127.0.0.1:9/v1",
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        provider_id = created.json()["id"]

        validated = await client.post(
            f"/api/settings/ai/providers/{provider_id}/validate",
            json={"model_id": "m"},
            headers=auth_headers,
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()["ok"] is False
        assert seen == []  # no use-time policy check on this path

    async def test_ollama_models_endpoint_does_consult_the_ssrf_policy(
        self, client, auth_headers, db_factory, monkeypatch
    ):
        """Control for AUDIT-4E-1: the sibling Ollama endpoint DOES validate the
        stored base_url at use time (Phase 16's fix), so the gap is not uniform."""
        import app.routers.settings as settings_router

        seen: list[str] = []
        real = settings_router.validate_base_url

        async def _spy(base_url, provider_type):
            seen.append(str(base_url))
            return await real(base_url, provider_type)

        monkeypatch.setattr(settings_router, "validate_base_url", _spy)

        async with db_factory() as db:
            provider = AiProvider(
                label="4e-models",
                provider_type="ollama",
                base_url="http://this-host-does-not-exist.invalid",
                enabled=True,
            )
            db.add(provider)
            await db.commit()
            provider_id = str(provider.id)

        resp = await client.get(
            f"/api/settings/ai/providers/{provider_id}/ollama-models", headers=auth_headers
        )
        assert resp.status_code == 422
        assert seen == ["http://this-host-does-not-exist.invalid"]

    async def test_resolve_task_hands_unvalidated_base_url_to_litellm(self, db_factory):
        """AUDIT-4E-1: the execution path detection's escalation uses passes the
        stored base_url straight into litellm, policy never consulted."""
        llm.clear_router_cache()
        async with db_factory() as db:
            provider = AiProvider(
                label="4e-exec",
                provider_type="openai_compatible",
                base_url=POLICY_REFUSED_URL,
                enabled=True,
            )
            db.add(provider)
            await db.flush()
            db.add(
                AiTaskAssignment(task=AiTaskType.explanation, provider_id=provider.id, model_id="m")
            )
            await db.commit()

            resolved = await llm.resolve_task(db, AiTaskType.explanation)

        assert resolved is not None
        assert resolved.router.model_list[0]["litellm_params"]["api_base"] == POLICY_REFUSED_URL
        with pytest.raises(SSRFBlockedError):
            assert_url_allowed(POLICY_REFUSED_URL)
        llm.clear_router_cache()


class _HangHandler(BaseHTTPRequestHandler):
    """Accepts a request and never answers it (a hung provider)."""

    def _hang(self) -> None:
        time.sleep(5)

    do_GET = _hang
    do_POST = _hang
    do_PUT = _hang

    def log_message(self, *args) -> None:
        return


@pytest.fixture
def hanging_provider_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HangHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class TestLlmCallBudgetOnAHungProvider:
    def test_router_configures_a_per_model_group_retry_budget(self):
        """AUDIT-4E-3: the Router's configured retry/cooldown budget is what
        bounds a hung call. Measured (scratch probes, 3 passes each):
        1 deployment -> 30.61 / 30.03 / 30.02 s; 2 keyed deployments ->
        60.67 / 60.08 / 60.05 s. The stall is therefore linear in the number
        of deployments (one per key) — `allowed_fails=0` cools only the
        deployment that just failed, so the retry walks to the next one."""
        primary = AiProvider(
            label="4e-primary", provider_type="openai_compatible", base_url="http://127.0.0.1:9"
        )
        fallback = AiProvider(
            label="4e-fallback", provider_type="openai_compatible", base_url="http://127.0.0.1:9"
        )
        router = llm._build_router(primary, "m", fallback, "m2")

        assert llm._REQUEST_TIMEOUT == 30
        assert llm._NUM_RETRIES == 2
        assert llm._ALLOWED_FAILS == 0
        assert llm._COOLDOWN_SECONDS == 60
        assert router.num_retries == llm._NUM_RETRIES
        assert {d["litellm_params"]["timeout"] for d in router.model_list} == {llm._REQUEST_TIMEOUT}
        assert router.fallbacks == [{llm._PRIMARY_ALIAS: [llm._FALLBACK_ALIAS]}]

    def test_every_key_is_its_own_deployment_and_its_own_timeout(self):
        """AUDIT-4E-3: a 10-key rotation pool is 10 litellm deployments sharing
        one alias, so one logical call can wait out up to 10 x timeout before
        degrading — 300 s of a 420 s scan soft limit."""
        from app.ai_config import MAX_KEYS_PER_PROVIDER, encrypt_keys

        provider = AiProvider(
            label="4e-pool",
            provider_type="openai_compatible",
            base_url="http://127.0.0.1:9",
            credentials_encrypted=encrypt_keys(
                [f"sk-4e-pool-key-{i:02d}-0123456789abcdef" for i in range(MAX_KEYS_PER_PROVIDER)]
            ),
        )
        deployments = llm._deployments(provider, "m", llm._PRIMARY_ALIAS)
        assert len(deployments) == MAX_KEYS_PER_PROVIDER == 10
        assert {d["model_name"] for d in deployments} == {llm._PRIMARY_ALIAS}
        assert len(deployments) * llm._REQUEST_TIMEOUT >= 300

    async def test_hung_deployment_degrades_after_one_timeout_budget(
        self, hanging_provider_url, monkeypatch
    ):
        """AUDIT-4E-3 (measured): the call waits out the full read timeout before
        the silent degradation the layer contract promises — bounded, but a real
        30 s (production) stall inside the scan's 420 s soft limit."""
        from app.ai_config import encrypt_keys

        monkeypatch.setattr(llm, "_REQUEST_TIMEOUT", 0.4)
        provider = AiProvider(
            label="4e-hang",
            provider_type="openai_compatible",
            base_url=hanging_provider_url,
            # a key is required or litellm's openai shim fails before any request
            credentials_encrypted=encrypt_keys(["sk-4e-hang-test-key-0123456789"]),
        )
        started = time.monotonic()
        ok, detail = await llm.validate_provider_call(provider, "hang-model")
        elapsed = time.monotonic() - started

        assert ok is False
        assert "timeout" in detail.lower()  # surfaced, not swallowed
        assert elapsed >= llm._REQUEST_TIMEOUT  # one full attempt, exactly as measured

    async def test_keyless_custom_endpoint_fails_fast_instead_of_hanging(
        self, hanging_provider_url
    ):
        """AUDIT-4E verified-clean: a keyless openai_compatible provider is
        rejected by litellm's openai shim before any socket is opened, so the
        fail-fast path never waits out the transport timeout."""
        provider = AiProvider(
            label="4e-keyless", provider_type="openai_compatible", base_url=hanging_provider_url
        )
        started = time.monotonic()
        ok, detail = await llm.validate_provider_call(provider, "hang-model")
        elapsed = time.monotonic() - started
        assert ok is False
        assert elapsed < llm._REQUEST_TIMEOUT  # never reached the transport
        assert "api" in detail.lower() or "key" in detail.lower()


class TestCatalogFetchAndOllamaTransport:
    async def test_fetch_live_catalog_never_consults_the_ssrf_policy(self, monkeypatch):
        """AUDIT-4E-2: the models.dev fetch performs outbound I/O and the policy
        module is never consulted (site/probe/favicon paths all are)."""
        policy_calls: list[tuple] = []

        def _spy(*args, **kwargs):
            policy_calls.append(args)
            raise AssertionError("policy must not be needed for a fixed constant URL")

        monkeypatch.setattr(ssrf, "assert_url_allowed", _spy)

        requested: list[str] = []

        class _FakeClient:
            async def get(self, url, **kwargs):
                requested.append(str(url))
                return httpx.Response(
                    200,
                    json={"providers": {}, "models": {}},
                    request=httpx.Request("GET", str(url)),
                )

        result = await ai_catalog.fetch_live_catalog(client=_FakeClient())
        assert result == {"providers": [], "models": []}
        assert requested == [ai_catalog.CATALOG_URL]
        assert policy_calls == []

    async def test_fetch_live_catalog_builds_an_unpinned_client(self, monkeypatch):
        """AUDIT-4E-2: the client it builds carries no SSRFPinningTransport, so
        the check-vs-connect rebinding window the raw-httpx stack pins shut is
        open on this fetch (same class as AUDIT-4D-3)."""
        recorded: dict = {}

        class _Recorder(httpx.AsyncClient):
            def __init__(self, **kwargs):
                recorded.update(kwargs)
                super().__init__(**kwargs)

            async def get(self, url, **kwargs):
                raise httpx.ConnectError("4e stop")

        monkeypatch.setattr(ai_catalog.httpx, "AsyncClient", _Recorder)
        assert await ai_catalog.fetch_live_catalog() is None  # degrades, never raises
        assert recorded["timeout"] == ai_catalog._FETCH_TIMEOUT
        assert "transport" not in recorded
        assert recorded.get("follow_redirects") in (None, False)

    def test_normalize_base_falls_back_to_the_docker_hostname(self):
        """AUDIT-4E-6: the module comment says a bare host install uses
        localhost, but None/"" resolve to the Docker service hostname — that
        expression's localhost fallback is dead while the *second* one (reached
        only by whitespace-only input) is live, so the two empty spellings
        disagree about which endpoint "no base_url" means."""
        assert ai_ollama.DEFAULT_OLLAMA_BASE_URL == "http://ollama:11434"
        assert ai_ollama.normalize_base(None) == "http://ollama:11434"
        assert ai_ollama.normalize_base("") == "http://ollama:11434"
        assert ai_ollama.normalize_base("   ") == "http://localhost:11434"

        ollama_provider = AiProvider(label="4e-ollama", provider_type="ollama", base_url=None)
        assert llm._litellm_api_base(ollama_provider) == "http://ollama:11434"
        # Third copy of the same "/v1 strip" rule, in the call path.
        assert (
            llm._litellm_api_base(
                AiProvider(
                    label="4e-v1", provider_type="ollama", base_url="http://ollama:11434/v1/"
                )
            )
            == "http://ollama:11434"
        )

    async def test_validate_base_url_refuses_the_seeded_default_on_a_bare_host(self):
        """AUDIT-4E-6: the seeded provider's URL does not resolve outside the
        compose network, so there the default provider is enabled-but-unusable
        (it is seeded with validate_url=False)."""
        with pytest.raises(ProviderConfigError):
            await validate_base_url("http://this-host-does-not-exist.invalid", "ollama")
        # ollama/openai_compatible alone get the private-network allowance.
        await validate_base_url("http://127.0.0.1:11434", "ollama")
        with pytest.raises(ProviderConfigError):
            await validate_base_url("http://127.0.0.1:11434", "google")

    async def test_ollama_pull_client_has_no_deadline(self, monkeypatch):
        """AUDIT-4E-7: /api/pull streams with timeout=None — no idle or total
        deadline exists for a stalled Ollama daemon (discovery calls have 15s)."""
        recorded: dict = {}

        class _Recorder(httpx.AsyncClient):
            def __init__(self, **kwargs):
                recorded.update(kwargs)
                super().__init__(**kwargs)

            def stream(self, *args, **kwargs):
                raise httpx.ConnectError("4e stop")

        monkeypatch.setattr(ai_ollama.httpx, "AsyncClient", _Recorder)
        with pytest.raises(ai_ollama.OllamaError):
            async for _ in ai_ollama.pull_stream("http://127.0.0.1:9", "m"):
                pass
        assert ai_ollama._PULL_TIMEOUT is None
        assert recorded["timeout"] is None
        assert ai_ollama._DISCOVERY_TIMEOUT == 15


class TestSecretRedactionCoverage:
    def test_scrub_only_catches_prefix_or_length_shaped_secrets(self):
        """AUDIT-4E-8: log redaction is heuristic (vendor prefixes + >=32-char
        opaque runs), so a short custom-endpoint key echoed by a provider error
        survives into the log line and into persisted validation_detail."""
        assert llm._scrub_secrets("Incorrect API key provided: shorty123") == (
            "Incorrect API key provided: shorty123"
        )
        long_key = "key sk-abcdefghijklmnopqrstuvwxyz123456 rejected"
        google_key = "Google key AIzaSyA1234567890abcdefg rejected"
        assert "[REDACTED]" in llm._scrub_secrets(long_key)
        assert "[REDACTED]" in llm._scrub_secrets(google_key)


class TestProviderCredentialsAreFernetAtRest:
    async def test_every_ai_provider_write_path_stores_fernet_ciphertext(self, db_factory):
        """AUDIT-4E positive verification: both credential write paths encrypt
        (Rule 4 — proved, not asserted), the redacted view never leaks the key,
        and a rotation replaces rather than appends the ciphertext."""
        from app.ai_config import provider_out
        from app.llm import provider_api_keys

        secret = "sk-4e-super-secret-material-0123456789abcdef"
        rotated = "sk-4e-second-secret-material-fedcba9876543210"

        async with db_factory() as db:
            provider = await create_provider(
                db, label="4e-fernet", provider_type="google", api_keys=[secret], base_url=None
            )
            await db.commit()
            provider_id = provider.id

        async with db_factory() as db:
            row = await db.scalar(select(AiProvider).where(AiProvider.id == provider_id))
            assert row is not None
            assert row.credentials_encrypted
            assert secret not in row.credentials_encrypted
            assert provider_api_keys(row) == [secret]
            assert secret not in json.dumps(provider_out(row))
            assert provider_out(row)["key_count"] == 1

            await update_provider(db, row, api_keys=[rotated])
            await db.commit()

        async with db_factory() as db:
            row = await db.scalar(select(AiProvider).where(AiProvider.id == provider_id))
            assert provider_api_keys(row) == [rotated]
            assert secret not in (row.credentials_encrypted or "")


class TestTorchOsvGateIsWiredAndCanFail:
    def test_gate_is_wired_into_ci_without_a_swallowing_operator(self):
        ci = (BACKEND_DIR.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        steps = [ln.strip() for ln in ci.splitlines() if "check_torch_osv.py" in ln]
        assert len(steps) == 1, steps
        assert "||" not in steps[0] and "; true" not in steps[0]
        assert "pip-audit" in ci  # the primary audit it complements still runs

    def test_torch_is_actually_present_in_the_audited_lockfile(self):
        tool = _load_tool("check_torch_osv")
        versions = tool.locked_torch_versions(tool.DEFAULT_LOCK_PATH)
        assert versions, "the gate would be vacuous without a torch entry"
        assert all(tool.strip_local_label(v) == "2.13.0" for v in versions)

    def test_advisory_makes_the_gate_exit_nonzero(self, monkeypatch):
        tool = _load_tool("check_torch_osv")
        monkeypatch.setattr(
            tool,
            "query_osv",
            lambda payload, url=tool.OSV_QUERY_URL: {
                "vulns": [{"id": "OSV-4E-SYNTHETIC", "summary": "synthetic advisory"}]
            },
        )
        assert tool.main([]) == 1

    def test_unverifiable_osv_fails_closed(self, monkeypatch):
        tool = _load_tool("check_torch_osv")

        def _boom(payload, url=tool.OSV_QUERY_URL):
            raise OSError("network down")

        monkeypatch.setattr(tool, "query_osv", _boom)
        monkeypatch.setattr(tool, "RETRY_BACKOFF_SECONDS", 0.0)
        assert tool.main([]) == 2

    def test_unreadable_lockfile_is_a_hard_error(self, tmp_path):
        tool = _load_tool("check_torch_osv")
        assert tool.main(["--lock", str(tmp_path / "absent.lock")]) == 2

    def test_lockfile_without_torch_is_a_pass(self, tmp_path):
        lock = tmp_path / "uv.lock"
        lock.write_text('[[package]]\nname = "httpx"\nversion = "0.28.1"\n', encoding="utf-8")
        tool = _load_tool("check_torch_osv")
        assert tool.main(["--lock", str(lock)]) == 0
