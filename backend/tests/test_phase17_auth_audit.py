"""Phase 17: brute-force defense on login + audit target_label overflow.

Finding A (login lockout): failed attempts are counted per-account in the
DB, trip an escalating lockout, are audited (auth.login_failed) and logged;
a dedicated tight per-IP limiter guards the login endpoint itself.
Finding B (audit label overflow): record_audit caps target_label to the
column width so long composite labels can no longer abort the caller's
commit (Postgres enforces VARCHAR(256); the old code 500'd on hook
create/update/delete and on user emails longer than 256 chars).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, User

TEST_PASSWORD = "correct horse battery staple"


async def _failed_login_rows(db_factory, email=None):
    async with db_factory() as db:
        query = select(AuditLog).where(AuditLog.action == "auth.login_failed")
        if email is not None:
            query = query.where(AuditLog.target_label == email)
        return list((await db.scalars(query.order_by(AuditLog.created_at))).all())


async def _user_row(db_factory, email):
    async with db_factory() as db:
        return await db.scalar(select(User).where(User.email == email))


async def _expire_lock(db_factory, email):
    """Force the persisted lock into the past without touching the counter."""
    from sqlalchemy import update

    async with db_factory() as db:
        await db.execute(
            update(User)
            .where(User.email == email)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


class TestLoginLockout:
    async def test_below_threshold_never_locks(self, client, admin_user):
        email = admin_user.email
        for i in range(4):  # threshold is 5
            r = await client.post(
                "/api/auth/login", json={"email": email, "password": f"wrong-{i}"}
            )
            assert r.status_code == 401
        r = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
        assert r.status_code == 200

    async def test_threshold_trips_lock_denies_even_correct_password_and_audits(
        self, client, db_factory, admin_user
    ):
        email = admin_user.email
        statuses = [
            (
                await client.post(
                    "/api/auth/login", json={"email": email, "password": f"wrong-{i}"}
                )
            ).status_code
            for i in range(5)
        ]
        assert statuses == [401] * 5

        rows = await _failed_login_rows(db_factory, email)
        assert [r.after_json["failed_attempts"] for r in rows] == [1, 2, 3, 4, 5]
        assert [r.after_json["reason"] for r in rows] == ["invalid_credentials"] * 5
        assert [r.after_json["lockout_engaged"] for r in rows] == [False] * 4 + [True]
        assert all(r.target_id == str(admin_user.id) for r in rows)

        # Locked: even the CORRECT password is denied (no mid-lock oracle).
        r = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
        assert r.status_code == 429
        retry_after = int(r.headers["Retry-After"])
        assert retry_after >= 1
        async with db_factory() as db:
            successful = list(
                (await db.scalars(select(AuditLog).where(AuditLog.action == "auth.login"))).all()
            )
        assert successful == []  # no login succeeded through the lockout

    async def test_lockout_persists_across_limiter_reset(self, client, admin_user):
        email = admin_user.email
        for i in range(5):
            await client.post("/api/auth/login", json={"email": email, "password": f"wrong-{i}"})
        from app.config import get_settings
        from app.ratelimit import reset_limiters

        get_settings.cache_clear()
        reset_limiters()
        r = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
        assert r.status_code == 429  # DB-persisted state, not in-memory

    async def test_second_lockout_is_longer_than_first(self, client, db_factory, admin_user):
        email = admin_user.email
        for i in range(5):
            await client.post("/api/auth/login", json={"email": email, "password": f"wrong-{i}"})
        first = int(
            (
                await client.post(
                    "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
                )
            ).headers["Retry-After"]
        )
        await _expire_lock(db_factory, email)

        # One more failure past expiry: counter -> 6, doubled duration.
        r = await client.post("/api/auth/login", json={"email": email, "password": "wrong-again"})
        assert r.status_code == 401
        second = int(
            (
                await client.post(
                    "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
                )
            ).headers["Retry-After"]
        )
        assert second > first

    async def test_successful_login_resets_counter(self, client, admin_user):
        email = admin_user.email
        for round_start in range(2):
            for i in range(4):
                r = await client.post(
                    "/api/auth/login",
                    json={"email": email, "password": f"w{round_start}-{i}"},
                )
                assert r.status_code == 401
            r = await client.post(
                "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
            )
            assert r.status_code == 200, "counter must reset on success"

    async def test_concurrent_failures_counted_atomically(self, client, db_factory, admin_user):
        email = admin_user.email

        async def one(i):
            return (
                await client.post("/api/auth/login", json={"email": email, "password": f"race-{i}"})
            ).status_code

        statuses = await asyncio.gather(*(one(i) for i in range(8)))
        assert set(statuses) <= {401, 429}
        assert 500 not in statuses
        user = await _user_row(db_factory, email)
        assert user.failed_login_attempts == 8  # exact count, no lost updates

    async def test_inactive_account_counts_as_failure_and_audits_reason(
        self, client, db_factory, admin_user
    ):
        from sqlalchemy import update

        email = admin_user.email
        async with db_factory() as db:
            await db.execute(update(User).where(User.email == email).values(is_active=False))
            await db.commit()
        r = await client.post("/api/auth/login", json={"email": email, "password": TEST_PASSWORD})
        assert r.status_code == 401
        user = await _user_row(db_factory, email)
        assert user.failed_login_attempts == 1
        rows = await _failed_login_rows(db_factory, email)
        assert rows[0].after_json["reason"] == "inactive_account"

    async def test_unknown_email_attempts_audited_without_account_state(self, client, db_factory):
        for i in range(3):
            r = await client.post(
                "/api/auth/login",
                json={"email": f"ghost{i}@example.com", "password": "x"},
            )
            assert r.status_code == 401
            assert r.json()["detail"] == "Invalid email or password"
        rows = await _failed_login_rows(db_factory)
        ghost = [r for r in rows if (r.target_label or "").startswith("ghost")]
        assert len(ghost) == 3
        assert all(r.target_id is None for r in ghost)
        assert all(r.after_json["reason"] == "unknown_account" for r in ghost)

    async def test_unicode_attempt_recorded_without_crash(self, client, db_factory):
        weird = "ターゲット@example.com"
        r = await client.post("/api/auth/login", json={"email": weird, "password": "x"})
        assert r.status_code == 401
        rows = await _failed_login_rows(db_factory, weird)
        assert len(rows) == 1
        assert rows[0].target_label == weird

    async def test_generic_message_identical_for_both_failure_shapes(self, client, admin_user):
        known = await client.post(
            "/api/auth/login",
            json={"email": admin_user.email, "password": "totally-wrong"},
        )
        unknown = await client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "totally-wrong"},
        )
        assert known.status_code == unknown.status_code == 401
        assert known.json()["detail"] == unknown.json()["detail"]

    async def test_dedicated_login_ip_limit_engages_independently(self, client, monkeypatch):
        from app import ratelimit
        from app.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_IP", "5")
        ratelimit.reset_limiters()
        try:
            statuses = []
            for i in range(7):  # valid credentials; pure request-rate pressure
                r = await client.post(
                    "/api/auth/login",
                    json={"email": f"u{i}@example.com", "password": TEST_PASSWORD},
                )
                statuses.append(r.status_code)
            assert statuses[:5] == [401] * 5  # unknown users, but under budget
            assert statuses[5:] == [429, 429]
            assert "Retry-After" in r.headers
        finally:
            get_settings.cache_clear()
            monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_IP", "0")
            ratelimit.reset_limiters()


class TestAuditTargetLabelCap:
    async def _make_site(self, client, auth_headers, name):
        r = await client.post(
            "/api/sites",
            json={
                "url": f"http://127.0.0.1/p17-{name[:12]}",
                "name": name,
                "allow_private_networks": True,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    async def test_long_hook_create_succeeds_with_capped_label(
        self, client, auth_headers, db_factory, stub_all_enqueues
    ):
        site_id = await self._make_site(client, auth_headers, "S" * 200)
        r = await client.post(
            f"/api/sites/{site_id}/remediation-hooks",
            json={
                "name": "H" * 200,
                "action_type": "custom_webhook",
                "webhook_url": "http://127.0.0.1:9/hook",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        hooks = (
            await client.get(f"/api/sites/{site_id}/remediation-hooks", headers=auth_headers)
        ).json()
        assert len(hooks) == 1
        async with db_factory() as db:
            row = await db.scalar(
                select(AuditLog).where(AuditLog.action == "remediation_hook.create")
            )
        assert row is not None
        assert len(row.target_label) == 256
        assert row.target_label.endswith("…")

    async def test_long_hook_rename_and_delete_succeed(
        self, client, auth_headers, db_factory, stub_all_enqueues
    ):
        # The audit's exact scenario: a hook under a LONG-NAMED site —
        # rename and delete both write the composite label and used to
        # abort with the same VARCHAR(256) overflow as create.
        site_id = await self._make_site(client, auth_headers, "S" * 200)
        hook_id = (
            await client.post(
                f"/api/sites/{site_id}/remediation-hooks",
                json={
                    "name": "ok-hook",
                    "action_type": "custom_webhook",
                    "webhook_url": "http://127.0.0.1:9/hook",
                },
                headers=auth_headers,
            )
        ).json()["id"]
        r = await client.patch(
            f"/api/sites/{site_id}/remediation-hooks/{hook_id}",
            json={"name": "H" * 200},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        r = await client.delete(
            f"/api/sites/{site_id}/remediation-hooks/{hook_id}", headers=auth_headers
        )
        assert r.status_code == 204
        async with db_factory() as db:
            actions = list(
                (
                    await db.scalars(
                        select(AuditLog.action).where(
                            AuditLog.action.in_(
                                ["remediation_hook.update", "remediation_hook.delete"]
                            )
                        )
                    )
                ).all()
            )
        assert sorted(actions) == ["remediation_hook.delete", "remediation_hook.update"]
        async with db_factory() as db:
            labels = list(
                (
                    await db.scalars(
                        select(AuditLog.target_label).where(
                            AuditLog.action == "remediation_hook.update"
                        )
                    )
                ).all()
            )
        assert len(labels[0]) <= 256

    async def test_boundary_exact_256_stored_verbatim(
        self, client, auth_headers, db_factory, stub_all_enqueues
    ):
        site_id = await self._make_site(client, auth_headers, "S" * 200)
        r = await client.post(
            f"/api/sites/{site_id}/remediation-hooks",
            json={
                "name": "h" * 54,  # 200 + 2 + 54 == 256 exactly
                "action_type": "custom_webhook",
                "webhook_url": "http://127.0.0.1:9/hook",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        async with db_factory() as db:
            row = await db.scalar(
                select(AuditLog).where(AuditLog.action == "remediation_hook.create")
            )
        assert len(row.target_label) == 256
        assert not row.target_label.endswith("…")

    async def test_long_email_user_create_and_login_work(
        self, client, auth_headers, db_factory, stub_all_enqueues
    ):
        long_email = "u" * 300 + "@example.com"
        r = await client.post(
            "/api/users",
            json={"email": long_email, "password": "AnotherPassword123!", "role": "viewer"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        r = await client.post(
            "/api/auth/login", json={"email": long_email, "password": "AnotherPassword123!"}
        )
        assert r.status_code == 200
        users = (await client.get("/api/users", headers=auth_headers)).json()
        assert any(u["email"] == long_email for u in users)


class TestCapLabelUnit:
    @pytest.mark.parametrize(
        ("text", "expected_len"),
        [
            ("", 0),
            ("x" * 255, 255),
            ("x" * 256, 256),
            ("x" * 257, 256),
            ("x" * 400, 256),
        ],
    )
    def test_lengths(self, text, expected_len):
        from app.audit import _cap_label

        capped = _cap_label(text)
        assert len(capped) == expected_len
        if len(text) > 256:
            assert capped.endswith("…")
            assert capped[:-1] == text[:255]
        else:
            assert capped == text

    def test_multibyte_counts_characters_not_bytes(self):
        from app.audit import _cap_label

        capped = _cap_label("タ" * 300)
        assert len(capped) == 256
        assert capped.endswith("…")
