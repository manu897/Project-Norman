"""rename sensors→nodes, add hub api_token_hash + last_seen_at, restructure readings

Carl architecture shifted from per-sensor MQTT to per-plant HTTPS batch
uploads from the hub. A "sensor" in old Norman vocabulary is now a "node"
(= a plant), with extra fields (mac, name, battery_pct, calibration) that
mirror the hub's `Node` JSON schema. Readings reference `node_id`.

Revision ID: 0002_nodes_and_hub_token
Revises: 0001_init
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_nodes_and_hub_token"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- hubs: add per-hub upload token + last_seen ----
    op.add_column("hubs", sa.Column("api_token_hash", sa.String(255)))
    op.add_column("hubs", sa.Column("last_seen_at", sa.DateTime(timezone=True)))

    # ---- readings: drop hypertable + table, recreate with node_id ----
    # The hypertable can't be ALTER-renamed cleanly across TimescaleDB versions,
    # and this branch hasn't shipped any data yet, so drop + recreate is safe.
    op.drop_index("ix_readings_sensor_id", table_name="readings")
    op.drop_table("readings")

    op.create_table(
        "readings",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("ts", "node_id", "metric"),
    )
    op.create_index("ix_readings_node_id", "readings", ["node_id"])
    op.execute("SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE)")

    # ---- sensors → nodes (drop + recreate with new columns) ----
    op.drop_index("ix_sensors_hub_id", table_name="sensors")
    op.drop_table("sensors")

    op.create_table(
        "nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "hub_id",
            sa.String(64),
            sa.ForeignKey("hubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("battery_pct", sa.Integer),
        sa.Column("calibration", JSONB),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_nodes_hub_id", "nodes", ["hub_id"])


def downgrade() -> None:
    op.drop_index("ix_nodes_hub_id", table_name="nodes")
    op.drop_table("nodes")
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

    op.drop_index("ix_readings_node_id", table_name="readings")
    op.drop_table("readings")
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

    op.drop_column("hubs", "last_seen_at")
    op.drop_column("hubs", "api_token_hash")
