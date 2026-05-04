"""init: users, hubs, sensors, readings (timescale hypertable), predictions

Revision ID: 0001_init
Revises:
Create Date: 2026-04-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "hubs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hubs_owner_id", "hubs", ["owner_id"])

    op.create_table(
        "sensors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "hub_id",
            sa.String(64),
            sa.ForeignKey("hubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False, server_default="bme680"),
        sa.Column("label", sa.String(255)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sensors_hub_id", "sensors", ["hub_id"])

    op.create_table(
        "readings",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sensor_id", sa.String(64), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("ts", "sensor_id", "metric"),
    )
    op.create_index("ix_readings_sensor_id", "readings", ["sensor_id"])
    op.execute("SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE)")

    op.create_table(
        "predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hub_id",
            sa.String(64),
            sa.ForeignKey("hubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    op.create_index("ix_predictions_hub_id", "predictions", ["hub_id"])
    op.create_index("ix_predictions_ts", "predictions", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_predictions_ts", table_name="predictions")
    op.drop_index("ix_predictions_hub_id", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_readings_sensor_id", table_name="readings")
    op.drop_table("readings")
    op.drop_index("ix_sensors_hub_id", table_name="sensors")
    op.drop_table("sensors")
    op.drop_index("ix_hubs_owner_id", table_name="hubs")
    op.drop_table("hubs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
