"""Phase 4 unit tests: crypto, settings store, alert content/dispatch
helpers, LLM plumbing (parsing/degradation), and report rendering.

No live network anywhere: SMTP/Apprise/Gemini/Ollama calls are exercised
through fakes and failure-injection — live delivery is verified against
the compose stack during phase sign-off.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.crypto as crypto
from app.alerting import (
    build_alert_content,
    build_telegram_apprise_url,
    build_test_content,
    deliver_to_channel,
    send_apprise,
    smtp_settings_usable,
)
from app.crypto import DecryptionError, decrypt_json, decrypt_text, encrypt_json, encrypt_text
from app.llm import (
    build_classification_prompt,
    build_explain_prompt,
    parse_classification,
)
from app.models import (
    Alert,
    AlertDelivery,
    AlertDeliveryStatus,
    NotificationChannel,
    NotificationChannelType,
    Scan,
    ScanStatus,
    ScanVerdict,
    Site,
)
from app.settings_store import SMTP_KEY, load_setting, save_setting
from worker.alert_tasks import _deliver_alert, top_layers_from_scores
from worker.llm_escalation import (
    ESCALATION_HIGH,
    ESCALATION_LOW,
    escalation_upgrades_verdict,
    should_escalate,
)
from worker.telegram_bot import parse_duration_minutes

# --- crypto ---


def test_encrypt_decrypt_round_trip():
    assert decrypt_text(encrypt_text("s3cret value")) == "s3cret value"
    payload = {"host": "smtp.example.com", "password": "hunter2!"}
    assert decrypt_json(encrypt_json(payload)) == payload


def test_decrypt_garbage_raises_decryption_error():
    with pytest.raises(DecryptionError):
        decrypt_text("not-a-fernet-token")
    with pytest.raises(DecryptionError):
        decrypt_json(encrypt_text("[1, 2, 3]"))  # valid JSON, not an object


def test_decrypt_with_rotated_key_raises(monkeypatch):
    token = encrypt_text("value")
    # Simulate a rotated CREDENTIALS_ENCRYPTION_KEY by clearing the cache
    # and pointing the settings at a different key.
    crypto._fernet.cache_clear()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "a-different-key-also-32-bytes-long!!")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(DecryptionError):
            decrypt_text(token)
    finally:
        get_settings.cache_clear()
        crypto._fernet.cache_clear()


# --- settings store ---


async def test_settings_store_round_trip(db_factory):
    async with db_factory() as db:
        assert await load_setting(db, SMTP_KEY) is None
        await save_setting(db, SMTP_KEY, {"host": "mail.example.com", "password": "pw"})
        loaded = await load_setting(db, SMTP_KEY)
        assert loaded == {"host": "mail.example.com", "password": "pw"}
        # Update overwrites in place.
        await save_setting(db, SMTP_KEY, {"host": "mail2.example.com"})
        assert (await load_setting(db, SMTP_KEY))["host"] == "mail2.example.com"


async def test_settings_store_undecryptable_row_is_unconfigured(db_factory):
    from app.models import AppSetting

    async with db_factory() as db:
        db.add(AppSetting(key="smtp", value_encrypted="corrupted-ciphertext"))
        await db.commit()
        assert await load_setting(db, SMTP_KEY) is None  # degrade, never raise


# --- alert content ---


def _content(**overrides):
    kwargs = dict(
        site_name="Example",
        site_url="https://example.com",
        risk_score=0.82,
        flag_threshold=0.5,
        top_layers=[{"label": "Known signatures", "score": 1.0}],
        scan_id="scan-1",
        site_id="site-1",
        detected_at="2026-07-17 12:00 UTC",
        base_url="http://localhost:8321",
    )
    kwargs.update(overrides)
    return build_alert_content(**kwargs)


def test_alert_content_renders_all_surfaces():
    content = _content()
    assert "82%" in content.title and "Example" in content.title
    assert "https://example.com" in content.body_text
    assert "Known signatures" in content.body_text
    assert "http://localhost:8321/sites/site-1/scans/scan-1" in content.body_text
    # Email HTML is premailer-inlined (style attributes, not <style> only).
    assert "style=" in content.email_html
    assert "Example" in content.email_html


def test_alert_content_escapes_hostile_site_name():
    content = _content(site_name='<script>alert("x")</script>')
    assert "<script>alert" not in content.email_html  # autoescaped


def test_test_content_identifies_channel_kind():
    content = build_test_content("telegram")
    assert "telegram" in content.body_text


def test_top_layers_orders_and_caps():
    scores = {
        "layer1_hash": {"score": 1.0, "skipped": False},
        "layer2_dom_structure": {"score": 0.3, "skipped": False},
        "layer4_visual_diff": {"score": 0.9, "skipped": False},
        "layer5_signatures": {"score": 0.95, "skipped": False},
        "layer6_security_metadata": {"score": 0.0, "skipped": False},  # zero excluded
        "layer8_semantics": {"score": 0.7, "skipped": True},  # skipped excluded
        "layer9_fusion": {"score": 0.99, "skipped": False},  # not a signal layer
    }
    top = top_layers_from_scores(scores)
    assert [t["label"] for t in top] == [
        "Content hash",
        "Known signatures",
        "Visual appearance",
        "DOM structure",
    ]


def test_telegram_apprise_url_shape():
    assert build_telegram_apprise_url("123:abc", "42") == "tgram://123:abc/42/"


# --- channel delivery routing (no live sends) ---


async def test_deliver_email_requires_recipient_and_smtp():
    content = build_test_content("email")
    ok, detail = await deliver_to_channel("email", {}, content, smtp=None, telegram=None)
    assert not ok and "recipient" in detail
    ok, detail = await deliver_to_channel(
        "email", {"to": "x@example.com"}, content, smtp=None, telegram=None
    )
    assert not ok and "SMTP is not configured" in detail


async def test_deliver_telegram_requires_token_and_chat():
    content = build_test_content("telegram")
    ok, detail = await deliver_to_channel("telegram", {}, content, smtp=None, telegram=None)
    assert not ok and "token" in detail.lower()
    ok, detail = await deliver_to_channel(
        "telegram", {}, content, smtp=None, telegram={"bot_token": "123:abc"}
    )
    assert not ok and "/start" in detail


async def test_deliver_unknown_type_fails_cleanly():
    ok, detail = await deliver_to_channel(
        "carrier_pigeon", {}, build_test_content("x"), smtp=None, telegram=None
    )
    assert not ok and "Unknown channel type" in detail


async def test_send_apprise_rejects_invalid_url():
    ok, detail = await send_apprise("definitely-not-a-url", build_test_content("x"), kind="x")
    assert not ok and "not a valid Apprise URL" in detail


def test_smtp_usable_requires_host_and_from():
    assert not smtp_settings_usable(None)
    assert not smtp_settings_usable({"host": "smtp.example.com"})
    assert smtp_settings_usable({"host": "smtp.example.com", "from_addr": "w@example.com"})


# --- worker alert delivery task (fakes, in-memory DB) ---


async def _flagged_scan_fixture(db_factory):
    async with db_factory() as db:
        site = Site(name="Example", url="https://example.com")
        db.add(site)
        await db.flush()
        scan = Scan(
            site_id=site.id,
            status=ScanStatus.completed,
            verdict=ScanVerdict.flagged,
            risk_score=0.9,
            layer_scores={"layer5_signatures": {"score": 1.0, "skipped": False}},
            finished_at=datetime.now(UTC),
        )
        db.add(scan)
        await db.flush()
        alert = Alert(site_id=site.id, scan_id=scan.id, risk_score=0.9)
        db.add(alert)
        await db.commit()
        return site.id, scan.id, alert.id


@pytest.fixture
def patched_task_session(db_factory, monkeypatch):
    """Point worker task modules' task_session at the test DB."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_session():
        async with db_factory() as session:
            yield session

    import worker.alert_tasks as alert_tasks

    monkeypatch.setattr(alert_tasks, "task_session", fake_session)
    return fake_session


async def test_deliver_alert_no_channels(db_factory, patched_task_session):
    _, _, alert_id = await _flagged_scan_fixture(db_factory)
    assert await _deliver_alert(alert_id) == "no-channels"


async def test_deliver_alert_records_failure_rows(db_factory, patched_task_session, monkeypatch):
    """A channel whose transport fails becomes a failed delivery row with
    a user-safe detail — and the task reports rather than raises."""
    site_id, _, alert_id = await _flagged_scan_fixture(db_factory)
    async with db_factory() as db:
        db.add(
            NotificationChannel(
                type=NotificationChannelType.apprise_url,
                name="Ops webhook",
                config_encrypted=crypto.encrypt_json(
                    {"url": "json://host/path", "kind": "webhook"}
                ),
            )
        )
        await db.commit()

    async def failing_send(url, content, *, kind):
        return False, "The webhook notification service rejected the message or was unreachable"

    import app.alerting as alerting

    monkeypatch.setattr(alerting, "send_apprise", failing_send)
    result = await _deliver_alert(alert_id)
    assert "failed=1" in result
    async with db_factory() as db:
        rows = (await db.scalars(select(AlertDelivery))).all()
        assert len(rows) == 1
        assert rows[0].status == AlertDeliveryStatus.failed
        assert "rejected" in rows[0].detail
        assert rows[0].channel_name == "Ops webhook"


async def test_deliver_alert_success_and_idempotence(db_factory, patched_task_session, monkeypatch):
    site_id, _, alert_id = await _flagged_scan_fixture(db_factory)
    async with db_factory() as db:
        db.add(
            NotificationChannel(
                type=NotificationChannelType.apprise_url,
                name="ntfy",
                config_encrypted=crypto.encrypt_json({"url": "ntfy://topic", "kind": "ntfy"}),
            )
        )
        await db.commit()

    calls = {"n": 0}

    async def ok_send(url, content, *, kind):
        calls["n"] += 1
        return True, "sent"

    import app.alerting as alerting

    monkeypatch.setattr(alerting, "send_apprise", ok_send)
    assert "sent=1" in await _deliver_alert(alert_id)
    # acks_late redelivery: a second run must not double-send.
    assert await _deliver_alert(alert_id) == "already-delivered"
    assert calls["n"] == 1


async def test_deliver_alert_muted_site_skips(db_factory, patched_task_session):
    site_id, _, alert_id = await _flagged_scan_fixture(db_factory)
    async with db_factory() as db:
        site = await db.scalar(select(Site).where(Site.id == site_id))
        site.muted_until = datetime.now(UTC) + timedelta(hours=2)
        db.add(
            NotificationChannel(
                type=NotificationChannelType.apprise_url,
                name="ntfy",
                config_encrypted=crypto.encrypt_json({"url": "ntfy://topic", "kind": "ntfy"}),
            )
        )
        await db.commit()
    assert "skipped=1" in await _deliver_alert(alert_id)
    async with db_factory() as db:
        row = await db.scalar(select(AlertDelivery))
        assert row.status == AlertDeliveryStatus.skipped
        assert "muted until" in row.detail


async def test_deliver_alert_undecryptable_channel_fails_visibly(db_factory, patched_task_session):
    _, _, alert_id = await _flagged_scan_fixture(db_factory)
    async with db_factory() as db:
        db.add(
            NotificationChannel(
                type=NotificationChannelType.apprise_url,
                name="Broken",
                config_encrypted="garbage-ciphertext",
            )
        )
        await db.commit()
    assert "failed=1" in await _deliver_alert(alert_id)
    async with db_factory() as db:
        row = await db.scalar(select(AlertDelivery))
        assert row.status == AlertDeliveryStatus.failed
        assert "re-save" in row.detail


async def test_deliver_alert_site_scoped_channel_isolation(
    db_factory, patched_task_session, monkeypatch
):
    """A channel scoped to site B must not receive site A's alerts."""
    _, _, alert_id = await _flagged_scan_fixture(db_factory)
    async with db_factory() as db:
        other = Site(name="Other", url="https://other.example.com")
        db.add(other)
        await db.flush()
        db.add(
            NotificationChannel(
                site_id=other.id,
                type=NotificationChannelType.apprise_url,
                name="Other-only",
                config_encrypted=crypto.encrypt_json({"url": "ntfy://other", "kind": "ntfy"}),
            )
        )
        await db.commit()
    assert await _deliver_alert(alert_id) == "no-channels"


# --- LLM plumbing ---


def test_parse_classification_happy_and_fenced():
    good = '{"classification": "defacement", "confidence": 0.9, "rationale": "obvious"}'
    parsed = parse_classification(good)
    assert parsed["classification"] == "defacement" and parsed["confidence"] == 0.9
    fenced = f"```json\n{good}\n```"
    assert parse_classification(fenced)["classification"] == "defacement"


def test_parse_classification_rejects_malformed():
    assert parse_classification("total nonsense") is None
    assert parse_classification('{"classification": "sideways"}') is None
    assert parse_classification('["not", "an", "object"]') is None
    # Confidence clamped, non-numeric tolerated.
    parsed = parse_classification('{"classification": "benign", "confidence": 7}')
    assert parsed["confidence"] == 1.0
    parsed = parse_classification('{"classification": "benign", "confidence": "high"}')
    assert parsed["confidence"] == 0.0


def test_should_escalate_band():
    assert not should_escalate(ESCALATION_LOW - 0.01, changed=True)
    assert should_escalate(ESCALATION_LOW, changed=True)
    assert should_escalate((ESCALATION_LOW + ESCALATION_HIGH) / 2, changed=True)
    assert not should_escalate(ESCALATION_HIGH, changed=True)
    assert not should_escalate(0.5, changed=False)  # unchanged scans never escalate


def test_escalation_upgrade_rules():
    assert escalation_upgrades_verdict(
        {"status": "ok", "classification": "defacement", "confidence": 0.8}
    )
    # Low confidence, benign, unclear, and failures never upgrade.
    assert not escalation_upgrades_verdict(
        {"status": "ok", "classification": "defacement", "confidence": 0.3}
    )
    assert not escalation_upgrades_verdict(
        {"status": "ok", "classification": "benign", "confidence": 1.0}
    )
    assert not escalation_upgrades_verdict({"status": "unavailable: no key"})
    assert not escalation_upgrades_verdict({"status": "unparseable reply", "provider": "gemini"})


def test_prompts_embed_the_exact_model_inputs():
    p = build_classification_prompt(
        site_url="https://example.com",
        risk_score=0.5,
        layer_scores={"layer5_signatures": {"score": 0.4, "skipped": False}},
        new_text="HACKED BY nobody",
    )
    assert "https://example.com" in p and "HACKED BY nobody" in p and '"classification"' in p
    e = build_explain_prompt(
        site_name="Example",
        site_url="https://example.com",
        verdict="flagged",
        risk_score=0.9,
        flag_threshold=0.5,
        layer_scores=None,
        findings_notes=["matched known defacement phrasing: HACKED BY"],
    )
    assert "Example" in e and "flagged" in e and "HACKED BY" in e


async def test_gemini_unavailable_without_key():
    from app.llm import LLMUnavailable, gemini_generate

    with pytest.raises(LLMUnavailable):
        await gemini_generate("", "hello")


async def test_ollama_unavailable_without_model():
    from app.llm import LLMUnavailable, ollama_generate

    with pytest.raises(LLMUnavailable):
        await ollama_generate("http://localhost:11434/v1", None, "hello")


# --- bot helpers ---


def test_parse_duration_minutes():
    assert parse_duration_minutes("45m") == 45
    assert parse_duration_minutes("2h") == 120
    assert parse_duration_minutes("1d") == 1440
    assert parse_duration_minutes("90") == 90
    assert parse_duration_minutes("0") == 0
    assert parse_duration_minutes("14d") == 7 * 24 * 60  # capped at 7 days
    assert parse_duration_minutes("soon") is None
    assert parse_duration_minutes("-5m") is None
    assert parse_duration_minutes("") is None
