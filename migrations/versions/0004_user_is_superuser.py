"""add users.is_superuser for the admin-only /v1/admin/* surface

Revision ID: 0004_user_is_superuser
Revises: 0003_rooms_node_kinds
Create Date: 2026-08-26

No self-service way to become a superuser — flip it directly in Postgres
after this migration lands:
    UPDATE users SET is_superuser = true WHERE email = '<the chosen account>';
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_is_superuser"
down_revision: str | None = "0003_rooms_node_kinds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_superuser")
