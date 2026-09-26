"""add password hash to users

Revision ID: 5e13b8f4c201
Revises: 3521d6a89124
Create Date: 2026-09-26 14:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "5e13b8f4c201"
down_revision: str | None = "3521d6a89124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), server_default="", nullable=False),
    )
    op.alter_column("users", "password_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "password_hash")
