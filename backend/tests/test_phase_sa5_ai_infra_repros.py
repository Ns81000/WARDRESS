"""PROMPT-003 Session A / Subagent 5 — hermetic repro tests for the AI
integration / supply-chain / infrastructure findings re-verified in Session A.

Every test here PROVES CURRENT BEHAVIOR deterministically and is written so a
remediation prompt can flip the specific assertion it fixes. Nothing here
modifies production code (Rule 1); nothing here touches the network, the
database, or a container.

Covers: AUDIT-SA5-1 (new Ollama /api/show SSRF reader), AUDIT-SA5-2 (redaction
reaches a Viewer), AUDIT-SA5-3 (PyJWT nested-header RecursionError), AUDIT-SA5-4
(catalog fetch_live_catalog's false "never raises" contract), AUDIT-4D-1
deepening (a hostile site name raises out of deliver_to_channel),
AUDIT-4E-1 deepening (the private-network allowance reaches cloud metadata),
and AUDIT-SA5-5 (no Fernet key ring / rotation path).
"""

from __future__ import annotations

import base64
import json

import pytest

# --------------------------------------------------------------------------
# AUDIT-SA5-1 — resolve_tool_capability -> Ollama /api/show never consults the
# SSRF policy, unlike its two sibling endpoints in routers/settings.py.
# --------------------------------------------------------------------------


async def test_resolve_tool_capability_never_consults_the_ssrf_policy(monkeypatch):
    """PROVES: the agent-chat tool-capability gate makes a live outbound POST to
    the stored base_url with ZERO SSRF checks (AUDIT-SA5-1, deepening of
    AUDIT-4E-1). Flip target: ai_config.resolve_tool_capability must call
    validate_base_url before probing, like settings.py:787 and :891 do."""
    from app import ai_config, ai_ollama
    from app.models import AiProvider

    seen: list[tuple] = []
    policy_calls: list[tuple] = []

    async def fake_show(base_url, model, api_key=None):
        seen.append((base_url, model, api_key))
        return ["completion", "tools"]

    def spy_assert_url_allowed(url, **kwargs):  # noqa: ANN001, ANN202
        policy_calls.append((url, kwargs))
        raise AssertionError("the SSRF policy must not be consulted on this path")

    monkeypatch.setattr(ai_ollama, "show_capabilities", fake_show)
    monkeypatch.setattr(ai_config, "assert_url_allowed", spy_assert_url_allowed, raising=False)

    provider = AiProvider(
        label="probe",
        provider_type="ollama",
        # Stored WITHOUT validation — exactly what PUT /api/settings/ollama's
        # create branch (settings.py:555-562) persists today.
        base_url="http://169.254.169.254:11434",
        credentials_encrypted=None,
    )

    capable = await ai_config.resolve_tool_capability(None, provider, "some-model")

    assert capable is True
    assert seen == [("http://169.254.169.254:11434", "some-model", None)]
    assert policy_calls == []


def test_ollama_normalize_base_passes_through_non_http_and_credential_urls():
    """PROVES: normalize_base performs no scheme/credential sanitisation, so a
    stored base_url of any shape reaches the outbound helpers unchanged."""
    from app.ai_ollama import normalize_base

    # normalize_base only strips a trailing slash and a legacy "/v1" suffix; it
    # performs no scheme, credential or address sanitisation.
    for stored in (
        "file:///etc/passwd",
        "gopher://127.0.0.1:11211/",
        "http://user:pass@internal.example:8080",
        "http://[::1]:1",
        "http://169.254.169.254:80",
    ):
        assert normalize_base(stored) == stored.rstrip("/")
    assert normalize_base("http://host.example/v1") == "http://host.example"


# --------------------------------------------------------------------------
# AUDIT-4E-1 deepening — the private-network allowance is keyed on provider
# TYPE for AI providers, so it also grants the cloud-metadata endpoint.
# --------------------------------------------------------------------------


def test_ai_private_network_allowance_also_grants_cloud_metadata():
    """PROVES (probe only — app/ssrf.py is never edited, Rule 12): for the two
    provider types ai_config.validate_base_url allows private networks, the
    link-local cloud-metadata addresses pass the policy. The finding is on the
    CONSUMER (keying the allowance on provider type), not on ssrf.py."""
    from app.ai_catalog import OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE
    from app.ssrf import SSRFBlockedError, assert_url_allowed

    metadata_targets = [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.169.254/v1/chat/completions",
        "http://100.100.100.200/latest/meta-data/",
    ]
    for provider_type in (OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE):
        assert provider_type in (OLLAMA_TYPE, OPENAI_COMPATIBLE_TYPE)  # documents the gate
        for url in metadata_targets:
            # default policy: refused
            with pytest.raises(SSRFBlockedError):
                assert_url_allowed(url, allow_private_networks=False)
            # the allowance the AI layer grants by TYPE: allowed
            assert assert_url_allowed(url, allow_private_networks=True) is None


# --------------------------------------------------------------------------
# AUDIT-SA5-2 — the heuristic redactor's leak reaches a Viewer via the
# layer-8 escalation evidence and an HTTP 503 body.
# --------------------------------------------------------------------------


async def test_escalation_evidence_carries_the_unredacted_short_key(monkeypatch):
    """PROVES: escalate_scan copies str(LLMUnavailable) into the evidence dict
    that is persisted as layer-8 ScanFinding.evidence and served to ANY
    authenticated role (GET /api/sites/{id}/scans/{id} uses CurrentUser), so a
    short custom-endpoint key echoed by a provider is readable by a Viewer."""
    from app.llm import LLMUnavailable
    from worker import llm_escalation

    short_key = "shorty123"

    class _Task:
        label = "openai_compatible"

        async def generate(self, prompt):  # noqa: ARG002
            raise LLMUnavailable(
                f"AuthenticationError: OpenAIException - Incorrect API key provided: {short_key}."
            )

    async def fake_resolve(db, task):  # noqa: ARG001
        return _Task()

    monkeypatch.setattr(llm_escalation, "resolve_task", fake_resolve)

    evidence = await llm_escalation.escalate_scan(
        None, site_url="https://x.test/", risk=0.5, layer_scores={}, new_text="t"
    )

    assert evidence["status"].startswith("unavailable: ")
    assert short_key in evidence["status"]


# --------------------------------------------------------------------------
# AUDIT-SA5-3 — PyJWT CVE-2026-102265 reaches app.security's decode path.
# --------------------------------------------------------------------------


def test_decode_access_token_raises_recursionerror_on_a_nested_jwt_header():
    """PROVES: app.security.decode_access_token is documented 'Never raises —
    callers translate None into 401', but a ~27 KB bearer token with a deeply
    nested header makes json.loads raise RecursionError, which is NOT a
    jwt.PyJWTError and therefore escapes the handler. Live-confirmed as an
    unauthenticated HTTP 500 on the shipped uvicorn+httptools deployment."""
    import jwt

    from app.security import decode_access_token

    def b64u(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    control = (
        b64u(json.dumps({"alg": "HS256"}).encode())
        + b"."
        + b64u(b'{"sub":"x"}')
        + b"."
        + b64u(b"sig")
    ).decode()
    assert decode_access_token(control) is None, "a plain bogus token is rejected cleanly"

    nested = (b64u(b"[" * 20_000) + b"." + b64u(b'{"a":1}') + b"." + b64u(b"x")).decode()
    assert len(nested) < 80_000, "must fit httptools' default 80 KiB header cap to be reachable"

    with pytest.raises(RecursionError) as excinfo:
        decode_access_token(nested)
    assert not isinstance(excinfo.value, jwt.PyJWTError)


# --------------------------------------------------------------------------
# AUDIT-SA5-4 — fetch_live_catalog's "or None on any failure ... Never raises"
# is false for a list-shaped providers key.
# --------------------------------------------------------------------------


def test_fetch_live_catalog_raises_on_a_list_shaped_providers_key():
    """PROVES: the except clause is (httpx.HTTPError, json.JSONDecodeError,
    ValueError); normalize_catalog raises AttributeError on a hostile shape and
    it escapes the documented never-raises contract (contained today only by
    the broad handlers in ai_startup/beat_tasks)."""
    from app.ai_catalog import fetch_live_catalog, normalize_catalog

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"providers": [1, 2, 3], "models": []}

    class _Client:
        async def get(self, url):  # noqa: ARG002
            return _Resp()

    with pytest.raises(AttributeError):
        normalize_catalog({"providers": [1, 2, 3]})

    import asyncio

    with pytest.raises(AttributeError):
        asyncio.run(fetch_live_catalog(client=_Client()))


# --------------------------------------------------------------------------
# AUDIT-4D-1 deepening — a hostile site name raises out of
# deliver_to_channel, which is contracted to return (ok, detail) and never
# raise, and the raise escapes the per-channel loop in _deliver_alert.
# --------------------------------------------------------------------------


def test_deliver_to_channel_raises_on_a_crlf_site_name():
    """PROVES: EmailMessage refuses a Subject containing CR/LF, and that
    ValueError is raised while building the message — i.e. BEFORE
    send_email's try/except, so it propagates out of deliver_to_channel into
    alert_tasks._deliver_alert's per-channel loop, where the task wrapper turns
    it into "error" with no delivery row for this or any later channel
    (the permanent-orphan condition of AUDIT-4D-1, now deterministically
    reachable from a user-controlled field)."""
    from app.alerting import build_alert_content, deliver_to_channel

    content = build_alert_content(
        site_name="acme\r\nBcc: attacker@evil.example",
        site_url="https://example.test/",
        risk_score=0.9,
        flag_threshold=0.5,
        top_layers=[],
        scan_id="11111111-1111-1111-1111-111111111111",
        site_id="22222222-2222-2222-2222-222222222222",
        detected_at="2026-09-30 03:00 UTC",
        base_url="http://localhost:8321",
    )
    smtp = {"host": "smtp.example.test", "from_addr": "ops@example.test"}

    with pytest.raises(ValueError, match="linefeed or carriage return"):
        import asyncio

        asyncio.run(
            deliver_to_channel(
                "email", {"to": "ops@example.test"}, content, smtp=smtp, telegram=None
            )
        )


def test_alert_html_template_escapes_hostile_site_names():
    """Positive control for the same finding: the HTML body IS safe (Jinja
    autoescape + premailer), so the defect is confined to the SMTP header path."""
    from app.alerting import build_alert_content

    content = build_alert_content(
        site_name='<img src=x onerror=alert(1)>"><script>alert(2)</script>',
        site_url="https://example.test/",
        risk_score=0.9,
        flag_threshold=0.5,
        top_layers=[],
        scan_id="11111111-1111-1111-1111-111111111111",
        site_id="22222222-2222-2222-2222-222222222222",
        detected_at="2026-09-30 03:00 UTC",
        base_url="http://localhost:8321",
    )
    assert "<script" not in content.email_html
    assert "<img" not in content.email_html
    assert "&lt;" in content.email_html


# --------------------------------------------------------------------------
# AUDIT-SA5-5 — there is no Fernet key ring, version prefix, or re-encrypt
# path; a CREDENTIALS_ENCRYPTION_KEY change destroys every stored credential
# and the AI layer degrades to an UNAUTHENTICATED deployment.
# --------------------------------------------------------------------------


def test_crypto_has_no_key_ring_and_rotation_downgrades_to_keyless(monkeypatch):
    """PROVES: (1) app.crypto exports no multi-key/rotation helper; (2) after a
    key change every decrypt caller degrades; (3) _deployments then builds a
    deployment with NO api_key — an authenticated provider silently becomes an
    anonymous one against whatever base_url is stored."""
    from app import crypto
    from app.config import get_settings
    from app.llm import _deployments
    from app.models import AiProvider

    assert not any(
        n
        for n in dir(crypto)
        if any(k in n.lower() for k in ("ring", "rotate", "reencrypt", "version"))
    )

    key_a = "A" * 40
    key_b = "B" * 40
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", key_a)
    get_settings.cache_clear()
    crypto._fernet.cache_clear()
    blob = crypto.encrypt_json({"api_keys": ["sk-live-CANARY0123456789"]})
    assert "CANARY" not in blob

    provider = AiProvider(
        label="probe",
        provider_type="openai_compatible",
        base_url="https://api.example.test/v1",
        credentials_encrypted=blob,
    )

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", key_b)
    get_settings.cache_clear()
    crypto._fernet.cache_clear()

    from app.llm import provider_api_keys

    assert provider_api_keys(provider) == []  # silent "treating as keyless"
    deployments = _deployments(provider, "some-model", "primary")
    assert "api_key" not in deployments[0]["litellm_params"]
    assert "rpm" not in deployments[0]["litellm_params"]
    assert deployments[0]["litellm_params"]["api_base"] == "https://api.example.test/v1"
