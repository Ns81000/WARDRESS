"""model_catalog_providers.env: json -> jsonb (align DB with the models)

Revision ID: m7n8p9q1r2s3
Revises: l6m7n8p9q1r2
Create Date: 2026-08-25 00:00:00.000000

Migration h2i3j4k5l6m7 created ``env`` as plain ``sa.JSON()`` while every
other dict column (and the model's ``JSONDict``) uses the
``JSON().with_variant(JSONB(), "postgresql")`` idiom — so production held a
``json`` column where the ORM metadata declares ``jsonb``, and
``alembic check`` reported a permanent modify_type drift item. Values are
app-written JSON objects, so the cast is lossless; jsonb's normalization
(dedup keys, key order) is invisible to the app, which only reads the
deserialized dict.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "m7n8p9q1r2s3"
down_revision: str | Sequence[str] | None = "l6m7n8p9q1r2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE model_catalog_providers
            ALTER COLUMN env TYPE JSONB USING env::JSONB
            """
        )
    # Other dialects have no JSONB; their generic JSON already matches the
    # metadata's non-postgres variant branch.


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE model_catalog_providers
            ALTER COLUMN env TYPE JSON USING env::JSON
            """
        )
