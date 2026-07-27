"""Regression tests for the 2026-07-21 audit correctness batch.

Covers:
- dom.py layer-3 urlparse guard (_safe_hostname)
- audit.py _redact recursion + URL userinfo scrubbing
- scanning.py is_stale uses started_at when available
- apikeys: viewer cannot create API keys (analyst+ only)
- auth: login emits an audit row
- sites: scan-now emits an audit row
- sites: enqueue-503 marks scan failed (no stranded pending row)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.audit import _redact
from app.scanning import is_stale
from worker.detection.dom import _safe_hostname, layer3_link_audit
from worker.detection.types import PageData

# ---------------------------------------------------------------------------
# _safe_hostname
# ---------------------------------------------------------------------------


def test_safe_hostname_normal() -> None:
    assert _safe_hostname("https://example.com/path") == "example.com"


def test_safe_hostname_malformed_ipv6() -> None:
    # urlparse raises ValueError on unterminated IPv6 literals — must not propagate
    assert _safe_hostname("http://[::1") == ""


def test_safe_hostname_none() -> None:
    assert _safe_hostname(None) == ""


def test_safe_hostname_empty() -> None:
    assert _safe_hostname("") == ""


# ---------------------------------------------------------------------------
# layer3 with malformed final_url
# ---------------------------------------------------------------------------


def _page(html: str = "<html></html>", final_url: str = "https://ok.com/") -> PageData:
    return PageData(html=html, final_url=final_url, content_hash="x" * 64)


def test_layer3_malformed_final_url_does_not_raise() -> None:
    """A malformed final_url must not crash layer 3 (fail-safe)."""
    bad = _page(final_url="http://[::1")
    result = layer3_link_audit(bad, bad)
    assert "score" in result
    assert result.get("score", 0.0) == 0.0


# ---------------------------------------------------------------------------
# _redact recursion
# ---------------------------------------------------------------------------


def test_redact_nested_sensitive_key() -> None:
    snap = {"smtp": {"password": "s3cr3t", "host": "mail.example.com"}}
    out = _redact(snap)
    assert out["smtp"]["password"] == "[redacted]"
    assert out["smtp"]["host"] == "mail.example.com"


def test_redact_url_userinfo_scrubbed() -> None:
    snap = {"webhook": "https://user:token@host.example.com/hook"}
    out = _redact(snap)
    assert "token" not in out["webhook"]
    assert "[redacted]" in out["webhook"]


def test_redact_top_level_sensitive_still_redacted() -> None:
    snap = {"api_key": "abc123", "name": "test"}
    out = _redact(snap)
    assert out["api_key"] == "[redacted]"
    assert out["name"] == "test"


def test_redact_none_passthrough() -> None:
    assert _redact(None) is None


def test_redact_list_value_recursed() -> None:
    snap = {"channels": [{"token": "secret", "name": "ch1"}]}
    out = _redact(snap)
    assert out["channels"][0]["token"] == "[redacted]"
    assert out["channels"][0]["name"] == "ch1"


# ---------------------------------------------------------------------------
# is_stale uses started_at
# ---------------------------------------------------------------------------


def test_is_stale_uses_started_at_not_created_at() -> None:
    """A scan created 20 min ago but started 2 min ago must NOT be stale."""
    now = datetime.now(UTC)
    created_at = now - timedelta(minutes=20)
    started_at = now - timedelta(minutes=2)
    assert not is_stale(created_at, started_at)


def test_is_stale_falls_back_to_created_at_when_no_started_at() -> None:
    old = datetime.now(UTC) - timedelta(minutes=20)
    assert is_stale(old, None)


def test_is_stale_started_at_old_is_stale() -> None:
    now = datetime.now(UTC)
    created_at = now - timedelta(minutes=5)
    started_at = now - timedelta(minutes=15)
    assert is_stale(created_at, started_at)


# ---------------------------------------------------------------------------
# API: viewer cannot create API keys
# ---------------------------------------------------------------------------



async def test_viewer_cannot_create_api_key(client, viewer_headers) -> None:
    resp = await client.post(
        "/api/api-keys",
        json={"label": "my-key"},
        headers=viewer_headers,
    )
    assert resp.status_code == 403



async def test_analyst_can_create_api_key(client, analyst_headers) -> None:
    resp = await client.post(
        "/api/api-keys",
        json={"label": "analyst-key"},
        headers=analyst_headers,
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# API: login emits an audit row
# ---------------------------------------------------------------------------



async def test_login_creates_audit_row(client, db_factory, admin_user) -> None:
    from sqlalchemy import select

    from app.models import AuditLog
    from tests.conftest import TEST_PASSWORD

    resp = await client.post(
        "/api/auth/login",
        json={"email": admin_user.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200

    async with db_factory() as db:
        row = await db.scalar(select(AuditLog).where(AuditLog.action == "auth.login"))
    assert row is not None
    assert row.actor_id == admin_user.id


# ---------------------------------------------------------------------------
# API: scan-now emits an audit row
# ---------------------------------------------------------------------------



async def test_scan_now_creates_audit_row(
    client, db_factory, auth_headers, stub_all_enqueues
) -> None:
    from sqlalchemy import select

    from app.models import AuditLog, Baseline, BaselineStatus, Site

    async with db_factory() as db:
        site = Site(name="audit-test", url="https://audit.example.com")
        db.add(site)
        await db.flush()
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="a" * 64,
        )
        db.add(baseline)
        await db.commit()
        site_id = site.id

    resp = await client.post(f"/api/sites/{site_id}/scan-now", headers=auth_headers)
    assert resp.status_code == 202

    async with db_factory() as db:
        row = await db.scalar(select(AuditLog).where(AuditLog.action == "scan.now"))
    assert row is not None


# ---------------------------------------------------------------------------
# API: enqueue-503 marks scan failed (no stranded pending row)
# ---------------------------------------------------------------------------



async def test_scan_now_503_marks_scan_failed(client, db_factory, auth_headers) -> None:
    """When the broker is down, scan-now must mark the pending row failed
    so the site is not 409-blocked on the next attempt."""
    from fastapi import HTTPException, status
    from sqlalchemy import select

    from app.models import Baseline, BaselineStatus, Scan, ScanStatus, Site

    async with db_factory() as db:
        site = Site(name="broker-down", url="https://broker-down.example.com")
        db.add(site)
        await db.flush()
        baseline = Baseline(
            site_id=site.id,
            status=BaselineStatus.ready,
            is_current=True,
            content_hash="b" * 64,
        )
        db.add(baseline)
        await db.commit()
        site_id = site.id

    def _raise(_id):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "queue down")

    with patch("app.services.enqueue_scan", side_effect=_raise):
        resp = await client.post(f"/api/sites/{site_id}/scan-now", headers=auth_headers)

    assert resp.status_code == 503

    # The scan row must be marked failed, not left pending.
    async with db_factory() as db:
        scans = (await db.scalars(select(Scan).where(Scan.site_id == site_id))).all()
    assert len(scans) == 1
    assert scans[0].status == ScanStatus.failed
