"""phase 4: notification channels, app settings, alerts, deliveries, mute, explanations

Revision ID: e9a2b7c15f04
Revises: d7e3a1c40f88
Create Date: 2026-07-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9a2b7c15f04"
down_revision: str | Sequence[str] | None = "d7e3a1c40f88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # §6 notification_channels: config JSON is Fernet-encrypted at rest
    # (app/crypto.py) — Apprise URLs embed webhook tokens and passwords.
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("site_id", sa.Uuid(), nullable=True),
        sa.Column(
            "type",
            sa.Enum("email", "telegram", "apprise_url", name="notification_channel_type"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_channels_site_id"),
        "notification_channels",
        ["site_id"],
        unique=False,
    )

    # Singleton encrypted config blobs (smtp / telegram / gemini / ollama).
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # §6 alerts: one per flagged scan; ack state for dashboard + bot /ack.
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("scan_id", sa.Uuid(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Uuid(), nullable=True),
        sa.Column("acknowledged_via", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scan_id"], ["scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alerts_site_id"), "alerts", ["site_id"], unique=False)
    op.create_index(op.f("ix_alerts_scan_id"), "alerts", ["scan_id"], unique=True)

    # Delivery attempts: failures are rows, not log lines — the UI shows
    # them (a broken channel must be visible, never crash a scan).
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=True),
        sa.Column("channel_name", sa.String(length=200), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "sent", "failed", "skipped", name="alert_delivery_status"),
            nullable=False,
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_alert_deliveries_alert_id"), "alert_deliveries", ["alert_id"], unique=False
    )

    # Sites: alert mute (bot /mute + dashboard). Scans still run.
    op.add_column("sites", sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True))

    # Scans: cached "Explain this incident" output (§8).
    op.add_column("scans", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("scans", sa.Column("explanation_provider", sa.String(length=32), nullable=True))
    op.add_column("scans", sa.Column("explanation_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("scans", "explanation_at")
    op.drop_column("scans", "explanation_provider")
    op.drop_column("scans", "explanation")
    op.drop_column("sites", "muted_until")
    op.drop_index(op.f("ix_alert_deliveries_alert_id"), table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    op.drop_index(op.f("ix_alerts_scan_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_site_id"), table_name="alerts")
    op.drop_table("alerts")
    op.drop_table("app_settings")
    op.drop_index(op.f("ix_notification_channels_site_id"), table_name="notification_channels")
    op.drop_table("notification_channels")
    # Autogenerate forgets Postgres enum types on downgrade — drop explicitly.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="alert_delivery_status").drop(bind, checkfirst=True)
        sa.Enum(name="notification_channel_type").drop(bind, checkfirst=True)
