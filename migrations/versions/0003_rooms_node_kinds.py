"""add rooms, node.kind/room_id/species, switch predictions to per-node

Aimed at Carl's end-state shape: three node kinds (plant/room/camera),
hub-scoped rooms, plant↔room assignment carried on the plant node,
predictions scoped per-plant-node (not per-hub).

Revision ID: 0003_rooms_node_kinds
Revises: 0002_nodes_and_hub_token
Create Date: 2026-06-12

NOTE: Alembic's own bookkeeping table (`alembic_version.version_num`) is a
plain VARCHAR(32) — that limit is Alembic's default, not something we
control per-project. Keep every revision id at or under 32 characters, or
`alembic upgrade` fails on the final UPDATE with StringDataRightTruncation
after the migration's real work has already run (and rolled back, since
Postgres DDL is transactional — no partial-apply risk, just a wasted run).
The original id here (0003_rooms_kind_per_node_predictions, 36 chars) hit
exactly that.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003_rooms_node_kinds"
down_revision: str | None = "0002_nodes_and_hub_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- new rooms table ----
    op.create_table(
        "rooms",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column(
            "hub_id",
            sa.String(64),
            sa.ForeignKey("hubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "hub_id"),
    )

    # ---- nodes: add kind/room_id/species ----
    op.add_column(
        "nodes",
        sa.Column("kind", sa.String(16), nullable=False, server_default="plant"),
    )
    op.add_column("nodes", sa.Column("room_id", sa.String(64), nullable=True))
    op.add_column("nodes", sa.Column("species", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_nodes_id_hub", "nodes", ["id", "hub_id"])

    # ---- predictions: rewrite as per-node ----
    # No data on pilot yet — drop + recreate is safe.
    op.drop_index("ix_predictions_ts", table_name="predictions")
    op.drop_index("ix_predictions_hub_id", table_name="predictions")
    op.drop_table("predictions")

    op.create_table(
        "predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    op.create_index("ix_predictions_node_id", "predictions", ["node_id"])
    op.create_index("ix_predictions_ts", "predictions", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_predictions_ts", table_name="predictions")
    op.drop_index("ix_predictions_node_id", table_name="predictions")
    op.drop_table("predictions")

    op.create_table(
        "predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hub_id",
            sa.String(64),
            sa.ForeignKey("hubs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    op.create_index("ix_predictions_hub_id", "predictions", ["hub_id"])
    op.create_index("ix_predictions_ts", "predictions", ["ts"])

    op.drop_constraint("uq_nodes_id_hub", "nodes", type_="unique")
    op.drop_column("nodes", "species")
    op.drop_column("nodes", "room_id")
    op.drop_column("nodes", "kind")

    op.drop_table("rooms")
