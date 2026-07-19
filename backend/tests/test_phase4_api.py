"""Phase 4 API tests: settings endpoints (SMTP/Telegram/Gemini/Ollama),
notification channels CRUD + redaction, alerts feed + ack, report
exports, explain endpoint degradation, and site mute semantics."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.crypto import decrypt_json
from app.models import (
    Alert,
    AlertDelivery,
    AlertDeliveryStatus,
    AppSetting,
    Baseline,
    BaselineStatus,
    NotificationChannel,
    Scan,
    ScanFinding,
    ScanStatus,
    ScanVerdict,
    Site,
)


async def _mk_site(db_factory, **kw) -> Site:
    async with db_factory() as db:
        site = Site(name=kw.pop("name", "Example"), url=kw.pop("url", "https://example.com"), **kw)
        db.add(site)
        await db.commit()
        await db.refresh(site)
        return site


async def _mk_completed_scan(db_factory, site_id, verdict=ScanVerdict.flagged, risk=0.9) -> Scan:
    async with db_factory() as db:
        baseline = Baseline(
            site_id=site_id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="a" * 64,
            captured_at=datetime.now(UTC),
        )
        db.add(baseline)
        await db.flush()
        scan = Scan(
            site_id=site_id,
            baseline_id=baseline.id,
            status=ScanStatus.completed,
            verdict=verdict,
            risk_score=risk,
            layer_scores={"layer5_signatures": {"score": 1.0, "skipped": False}},
            finished_at=datetime.now(UTC),
        )
        db.add(scan)
        await db.flush()
        db.add(
            ScanFinding(
                scan_id=scan.id,
                layer=5,
                layer_key="layer5_signatures",
                score=1.0,
                skipped=False,
                evidence={"matches": [{"matched": "HACKED BY", "strength": "strong"}]},
            )
        )
        await db.commit()
        await db.refresh(scan)
        return scan


# --- SMTP settings ---


async def test_smtp_settings_round_trip_and_redaction(client, auth_headers):
    resp = await client.get("/api/settings/smtp", headers=auth_headers)
    assert resp.status_code == 200 and resp.json()["configured"] is False

    resp = await client.put(
        "/api/settings/smtp",
        json={
            "host": "smtp.example.com",
            "port": 587,
            "security": "starttls",
            "username": "warden",
            "password": "app-password-123",
            "from_addr": "wardress@example.com",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["has_password"] is True
    assert "app-password-123" not in resp.text  # never round-trips

    # Editing without a password field keeps the stored password.
    resp = await client.put(
        "/api/settings/smtp",
        json={"host": "smtp2.example.com", "from_addr": "wardress@example.com"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["has_password"] is True
    # Explicit empty string clears it.
    resp = await client.put(
        "/api/settings/smtp",
        json={"host": "smtp2.example.com", "from_addr": "wardress@example.com", "password": ""},
        headers=auth_headers,
    )
    assert resp.json()["has_password"] is False


async def test_smtp_settings_encrypted_at_rest(client, auth_headers, db_factory):
    await client.put(
        "/api/settings/smtp",
        json={
            "host": "smtp.example.com",
            "from_addr": "w@example.com",
            "password": "sup3rsecret",
        },
        headers=auth_headers,
    )
    async with db_factory() as db:
        row = await db.scalar(select(AppSetting).where(AppSetting.key == "smtp"))
        assert row is not None
        assert "sup3rsecret" not in row.value_encrypted
        assert decrypt_json(row.value_encrypted)["password"] == "sup3rsecret"


async def test_smtp_validation_rejects_nonsense(client, auth_headers):
    resp = await client.put(
        "/api/settings/smtp",
        json={"host": "smtp.example.com", "from_addr": "not-an-email"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    resp = await client.put(
        "/api/settings/smtp",
        json={"host": "smtp.example.com", "from_addr": "w@example.com", "security": "psychic"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    resp = await client.put(
        "/api/settings/smtp",
        json={"host": "smtp.example.com", "from_addr": "w@example.com", "port": 99999},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_smtp_test_without_config_is_clean_failure(client, auth_headers):
    resp = await client.post(
        "/api/settings/smtp/test", json={"to": "me@example.com"}, headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and "not configured" in body["detail"]


async def test_smtp_test_accepts_inline_unsaved_settings(client, auth_headers, monkeypatch):
    """§8: the test button gates Save, so the endpoint must exercise the
    form's values before they exist in the DB."""
    captured = {}

    async def fake_send(smtp, to_addr, content):
        captured.update(smtp, to=to_addr)
        return True, "sent"

    import app.routers.settings as settings_router

    monkeypatch.setattr(settings_router, "send_email", fake_send)
    resp = await client.post(
        "/api/settings/smtp/test",
        json={
            "to": "me@example.com",
            "settings": {
                "host": "smtp.unsaved.example",
                "port": 2525,
                "security": "none",
                "password": "inline-pw",
                "from_addr": "w@example.com",
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert captured["host"] == "smtp.unsaved.example"
    assert captured["port"] == 2525
    assert captured["password"] == "inline-pw"
    assert captured["to"] == "me@example.com"
    # Nothing was persisted by the test call.
    resp = await client.get("/api/settings/smtp", headers=auth_headers)
    assert resp.json()["configured"] is False


async def test_smtp_test_inline_falls_back_to_stored_password(client, auth_headers, monkeypatch):
    await client.put(
        "/api/settings/smtp",
        json={"host": "smtp.example.com", "from_addr": "w@example.com", "password": "stored-pw"},
        headers=auth_headers,
    )
    captured = {}

    async def fake_send(smtp, to_addr, content):
        captured.update(smtp)
        return True, "sent"

    import app.routers.settings as settings_router

    monkeypatch.setattr(settings_router, "send_email", fake_send)
    resp = await client.post(
        "/api/settings/smtp/test",
        json={
            "to": "me@example.com",
            # Editing the host but not retyping the password.
            "settings": {"host": "smtp2.example.com", "from_addr": "w@example.com"},
        },
        headers=auth_headers,
    )
    assert resp.json()["ok"] is True
    assert captured["host"] == "smtp2.example.com"
    assert captured["password"] == "stored-pw"


# --- Telegram settings ---


async def test_telegram_settings_flow(client, auth_headers):
    resp = await client.get("/api/settings/telegram", headers=auth_headers)
    assert resp.json()["configured"] is False

    resp = await client.put(
        "/api/settings/telegram",
        json={"bot_token": "1234567890:AAExampleTokenBody"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["chat_id"] is None  # captured later by /start
    assert "AAExampleTokenBody" not in resp.text  # redacted hint only

    # Malformed token rejected with guidance.
    resp = await client.put(
        "/api/settings/telegram", json={"bot_token": "not a token"}, headers=auth_headers
    )
    assert resp.status_code == 422

    # Clearing works.
    resp = await client.put("/api/settings/telegram", json={"bot_token": ""}, headers=auth_headers)
    assert resp.json()["configured"] is False


async def test_telegram_new_token_clears_captured_chat(client, auth_headers, db_factory):
    from app.settings_store import TELEGRAM_KEY, load_setting, save_setting

    async with db_factory() as db:
        await save_setting(
            db, TELEGRAM_KEY, {"bot_token": "111:aaa", "chat_id": "42", "chat_captured_at": "x"}
        )
    resp = await client.put(
        "/api/settings/telegram", json={"bot_token": "222:bbb"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["chat_id"] is None  # old capture belonged to the old bot
    async with db_factory() as db:
        stored = await load_setting(db, TELEGRAM_KEY)
        assert stored["bot_token"] == "222:bbb" and "chat_id" not in stored


async def test_telegram_test_requires_capture(client, auth_headers):
    await client.put(
        "/api/settings/telegram", json={"bot_token": "111:aaa"}, headers={**auth_headers}
    )
    resp = await client.post("/api/settings/telegram/test", headers=auth_headers)
    body = resp.json()
    assert body["ok"] is False and "/start" in body["detail"]


async def test_telegram_acting_user_link(client, auth_headers, admin_user):
    """The bot's assistant acts as a real RBAC user; linking one round-trips
    the id + email, and an unknown/cleared link reads back as unset."""
    await client.put(
        "/api/settings/telegram", json={"bot_token": "111:aaa"}, headers=auth_headers
    )
    # Link the admin as the acting user.
    resp = await client.put(
        "/api/settings/telegram",
        json={"acting_user_id": str(admin_user.id)},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["acting_user_id"] == str(admin_user.id)
    assert body["acting_user_email"] == admin_user.email

    # A GET reflects the same link.
    resp = await client.get("/api/settings/telegram", headers=auth_headers)
    assert resp.json()["acting_user_id"] == str(admin_user.id)

    # An unknown user id is rejected (fail closed, no silent link).
    resp = await client.put(
        "/api/settings/telegram",
        json={"acting_user_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # Clearing the link ("") drops it without touching the token.
    resp = await client.put(
        "/api/settings/telegram", json={"acting_user_id": ""}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["acting_user_id"] is None
    assert resp.json()["configured"] is True  # token untouched


# --- Gemini / Ollama settings ---


async def test_gemini_settings_flow(client, auth_headers):
    resp = await client.get("/api/settings/gemini", headers=auth_headers)
    body = resp.json()
    assert body["configured"] is False and body["model"] == "gemini-flash-latest"

    resp = await client.put(
        "/api/settings/gemini", json={"api_key": "AIzaFakeKey123456"}, headers=auth_headers
    )
    body = resp.json()
    assert body["configured"] is True and body["enabled"] is True
    assert "AIzaFakeKey123456" not in resp.text

    resp = await client.put("/api/settings/gemini", json={"api_key": ""}, headers=auth_headers)
    assert resp.json()["configured"] is False


async def test_ollama_settings_flow(client, auth_headers):
    resp = await client.get("/api/settings/ollama", headers=auth_headers)
    assert resp.json()["configured"] is False

    resp = await client.put(
        "/api/settings/ollama",
        json={"enabled": True, "model": "llama3.2"},
        headers=auth_headers,
    )
    body = resp.json()
    assert body["configured"] is True and body["enabled"] is True and body["model"] == "llama3.2"


async def test_settings_require_auth(client):
    for path in (
        "/api/settings/smtp",
        "/api/settings/telegram",
        "/api/settings/gemini",
        "/api/settings/ollama",
    ):
        resp = await client.get(path)
        assert resp.status_code == 401, path


# --- Notification channels ---


async def test_channel_crud_and_redaction(client, auth_headers, db_factory):
    # ntfy channel (Apprise URL).
    resp = await client.post(
        "/api/notification-channels",
        json={
            "type": "apprise_url",
            "name": "Team ntfy",
            "url": "ntfy://wardress-alerts",
            "kind": "ntfy",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["target_hint"] == "ntfy://..."
    assert "wardress-alerts" not in resp.text  # topic redacted
    channel_id = body["id"]

    # Stored encrypted.
    async with db_factory() as db:
        row = await db.scalar(select(NotificationChannel))
        assert "wardress-alerts" not in row.config_encrypted

    # Listing shows it; disabling works.
    resp = await client.get("/api/notification-channels", headers=auth_headers)
    assert len(resp.json()) == 1
    resp = await client.patch(
        f"/api/notification-channels/{channel_id}",
        json={"is_active": False},
        headers=auth_headers,
    )
    assert resp.json()["is_active"] is False

    resp = await client.delete(f"/api/notification-channels/{channel_id}", headers=auth_headers)
    assert resp.status_code == 204
    resp = await client.get("/api/notification-channels", headers=auth_headers)
    assert resp.json() == []


async def test_channel_validation(client, auth_headers):
    # Email channel needs a plausible recipient.
    resp = await client.post(
        "/api/notification-channels",
        json={"type": "email", "name": "Ops", "to": "not-an-address"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # Apprise channel needs a URL Apprise recognizes.
    resp = await client.post(
        "/api/notification-channels",
        json={"type": "apprise_url", "name": "Bad", "url": "carrier-pigeon://coop"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    # Site-scoped channel 404s on a bogus site.
    resp = await client.post(
        "/api/notification-channels",
        json={
            "type": "apprise_url",
            "name": "Scoped",
            "url": "ntfy://topic",
            "site_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_email_channel_creation(client, auth_headers):
    resp = await client.post(
        "/api/notification-channels",
        json={"type": "email", "name": "On-call", "to": "oncall@example.com"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["target_hint"] == "oncall@example.com"


async def test_channel_test_endpoint_degrades_cleanly(client, auth_headers):
    resp = await client.post(
        "/api/notification-channels",
        json={"type": "email", "name": "On-call", "to": "oncall@example.com"},
        headers=auth_headers,
    )
    channel_id = resp.json()["id"]
    resp = await client.post(f"/api/notification-channels/{channel_id}/test", headers=auth_headers)
    body = resp.json()
    assert resp.status_code == 200 and body["ok"] is False
    assert "SMTP is not configured" in body["detail"]


# --- Alerts feed + ack ---


async def test_alerts_feed_and_ack(client, auth_headers, db_factory):
    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    async with db_factory() as db:
        alert = Alert(site_id=site.id, scan_id=scan.id, risk_score=0.9)
        db.add(alert)
        await db.flush()
        db.add(
            AlertDelivery(
                alert_id=alert.id,
                channel_name="Ops webhook",
                channel_type="apprise_url",
                status=AlertDeliveryStatus.failed,
                detail="The webhook notification service rejected the message",
                finished_at=datetime.now(UTC),
            )
        )
        await db.commit()
        alert_id = alert.id

    resp = await client.get("/api/alerts", headers=auth_headers)
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["site_name"] == "Example"
    assert item["deliveries"][0]["status"] == "failed"
    assert "rejected" in item["deliveries"][0]["detail"]

    # Ack is idempotent.
    resp = await client.post(f"/api/alerts/{alert_id}/ack", headers=auth_headers)
    assert resp.status_code == 200
    first_ack = resp.json()["acknowledged_at"]
    assert first_ack is not None and resp.json()["acknowledged_via"] == "dashboard"
    resp = await client.post(f"/api/alerts/{alert_id}/ack", headers=auth_headers)
    # SQLite returns the stored timestamp naive on re-read; compare the
    # instant, not the string (Postgres serves both aware).
    second_ack = resp.json()["acknowledged_at"]
    assert second_ack is not None
    assert second_ack.rstrip("Z") == first_ack.rstrip("Z")

    # Unacknowledged filter now excludes it.
    resp = await client.get("/api/alerts?unacknowledged_only=true", headers=auth_headers)
    assert resp.json()["total"] == 0


async def test_alert_ack_404(client, auth_headers):
    resp = await client.post(f"/api/alerts/{uuid.uuid4()}/ack", headers=auth_headers)
    assert resp.status_code == 404


# --- Site mute ---


async def test_site_mute_and_unmute(client, auth_headers, db_factory):
    site = await _mk_site(db_factory)
    resp = await client.patch(
        f"/api/sites/{site.id}", json={"mute_minutes": 120}, headers=auth_headers
    )
    assert resp.status_code == 200
    muted_until = resp.json()["muted_until"]
    assert muted_until is not None
    resp = await client.patch(
        f"/api/sites/{site.id}", json={"mute_minutes": 0}, headers=auth_headers
    )
    assert resp.json()["muted_until"] is None
    # Out-of-range rejected.
    resp = await client.patch(
        f"/api/sites/{site.id}", json={"mute_minutes": 999999}, headers=auth_headers
    )
    assert resp.status_code == 422


# --- Reports ---


async def test_markdown_report_export(client, auth_headers, db_factory):
    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    resp = await client.get(f"/api/reports/{scan.id}/markdown", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.text
    assert "# Wardress incident report — Example" in text
    assert "Layer 5 — Signature/keyword match" in text
    assert "HACKED BY" in text
    assert "Flagged" in text


async def test_report_404_for_missing_or_unfinished(client, auth_headers, db_factory):
    resp = await client.get(f"/api/reports/{uuid.uuid4()}/markdown", headers=auth_headers)
    assert resp.status_code == 404
    site = await _mk_site(db_factory)
    async with db_factory() as db:
        scan = Scan(site_id=site.id, status=ScanStatus.running)
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
    resp = await client.get(f"/api/reports/{scan.id}/markdown", headers=auth_headers)
    assert resp.status_code == 404  # unfinished scans have no report


async def test_report_requires_auth(client, db_factory):
    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    resp = await client.get(f"/api/reports/{scan.id}/markdown")
    assert resp.status_code == 401
    resp = await client.get(f"/api/reports/{scan.id}/pdf")
    assert resp.status_code == 401


async def test_markdown_report_bundles_zip_with_assets(
    client, auth_headers, db_factory, tmp_path, monkeypatch
):
    """When screenshots exist on disk, the Markdown export is a ZIP with
    report.md + an assets/ directory the image links resolve into."""
    import io
    import zipfile

    from app.config import get_settings

    # Point the artifacts root at a tmp dir and write real screenshot files.
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    get_settings.cache_clear()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # minimal PNG-ish payload

    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    async with db_factory() as db:
        s = await db.scalar(select(Scan).where(Scan.id == scan.id))
        baseline = await db.scalar(select(Baseline).where(Baseline.id == s.baseline_id))
        base_dir = tmp_path / "baselines" / str(baseline.id)
        scan_dir = tmp_path / "scans" / str(s.id)
        base_dir.mkdir(parents=True)
        scan_dir.mkdir(parents=True)
        (base_dir / "screenshot.png").write_bytes(png)
        (scan_dir / "screenshot.png").write_bytes(png)
        baseline.screenshot_path = f"baselines/{baseline.id}/screenshot.png"
        s.screenshot_path = f"scans/{s.id}/screenshot.png"
        await db.commit()

    resp = await client.get(f"/api/reports/{scan.id}/markdown", headers=auth_headers)
    get_settings.cache_clear()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")
    assert resp.headers["content-disposition"].endswith('.zip"')

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert "report.md" in names
    assert "assets/baseline.png" in names
    assert "assets/current-scan.png" in names
    assert "assets/timeline.svg" in names
    body = zf.read("report.md").decode("utf-8")
    assert "![Trusted baseline](assets/baseline.png)" in body
    assert "![This scan](assets/current-scan.png)" in body


async def test_markdown_report_escapes_pipes_in_evidence(client, auth_headers, db_factory):
    """Evidence containing markdown table syntax must not corrupt the
    table layout."""
    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    async with db_factory() as db:
        finding = await db.scalar(select(ScanFinding).where(ScanFinding.scan_id == scan.id))
        finding.evidence = {"matches": [{"matched": "a|b|c", "strength": "strong"}]}
        await db.commit()
    resp = await client.get(f"/api/reports/{scan.id}/markdown", headers=auth_headers)
    assert resp.status_code == 200
    for line in resp.text.splitlines():
        if "a/b/c" in line:
            break
    else:
        pytest.fail("pipe-bearing evidence not found in sanitized form")


# --- Explain endpoint ---


async def test_explain_503_when_no_provider(client, auth_headers, db_factory):
    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    resp = await client.post(f"/api/sites/{site.id}/scans/{scan.id}/explain", headers=auth_headers)
    assert resp.status_code == 503
    assert "No AI provider" in resp.json()["detail"]


async def test_explain_404s(client, auth_headers, db_factory):
    site = await _mk_site(db_factory)
    resp = await client.post(
        f"/api/sites/{site.id}/scans/{uuid.uuid4()}/explain", headers=auth_headers
    )
    assert resp.status_code == 404
    # Cross-site scan id must 404, not leak.
    other = await _mk_site(db_factory, name="Other", url="https://other.example.com")
    scan = await _mk_completed_scan(db_factory, site.id)
    resp = await client.post(f"/api/sites/{other.id}/scans/{scan.id}/explain", headers=auth_headers)
    assert resp.status_code == 404


async def test_explain_returns_cache_without_provider(client, auth_headers, db_factory):
    """A previously-generated explanation stays readable even after the
    provider is unconfigured."""
    site = await _mk_site(db_factory)
    scan = await _mk_completed_scan(db_factory, site.id)
    async with db_factory() as db:
        row = await db.scalar(select(Scan).where(Scan.id == scan.id))
        row.explanation = "Cached summary."
        row.explanation_provider = "gemini"
        row.explanation_at = datetime.now(UTC)
        await db.commit()
    resp = await client.post(f"/api/sites/{site.id}/scans/{scan.id}/explain", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True and body["explanation"] == "Cached summary."
    # The scan detail response carries it too.
    resp = await client.get(f"/api/sites/{site.id}/scans/{scan.id}", headers=auth_headers)
    assert resp.json()["explanation"] == "Cached summary."


# --- OpenAPI completeness (§15: every new endpoint documented) ---


async def test_phase4_endpoints_in_openapi(client):
    resp = await client.get("/openapi.json")
    paths = resp.json()["paths"]
    for path in (
        "/api/settings/smtp",
        "/api/settings/smtp/test",
        "/api/settings/telegram",
        "/api/settings/telegram/test",
        "/api/settings/gemini",
        "/api/settings/gemini/test",
        "/api/settings/ollama",
        "/api/settings/ollama/test",
        "/api/notification-channels",
        "/api/notification-channels/{channel_id}",
        "/api/notification-channels/{channel_id}/test",
        "/api/alerts",
        "/api/alerts/{alert_id}",
        "/api/alerts/{alert_id}/ack",
        "/api/reports/{scan_id}/pdf",
        "/api/reports/{scan_id}/markdown",
        "/api/sites/{site_id}/scans/{scan_id}/explain",
    ):
        assert path in paths, f"{path} missing from OpenAPI"
