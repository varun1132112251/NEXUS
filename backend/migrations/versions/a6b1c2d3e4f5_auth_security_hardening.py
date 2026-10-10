"""harden authentication tokens and recovery sessions

Revision ID: a6b1c2d3e4f5
Revises: e8f9a0b1c2d3, f4b8d2e91a30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6b1c2d3e4f5"
down_revision: str | Sequence[str] | None = ("e8f9a0b1c2d3", "f4b8d2e91a30")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_version", sa.Integer(), server_default=sa.text("1"), nullable=False))
    op.add_column("auth_tokens", sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.create_index(
        "ix_auth_tokens_email_purpose_created",
        "auth_tokens",
        ["email", "purpose", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_email_purpose_created", table_name="auth_tokens")
    op.drop_column("auth_tokens", "failed_attempts")
    op.drop_column("users", "auth_version")
