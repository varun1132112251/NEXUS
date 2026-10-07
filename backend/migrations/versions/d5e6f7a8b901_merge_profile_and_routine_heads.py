"""merge profile and routine migration heads

Revision ID: d5e6f7a8b901
Revises: 7c3f1e2a4b10, c3d4e5f60718
Create Date: 2026-10-07 15:30:00.000000
"""

from collections.abc import Sequence

revision: str = "d5e6f7a8b901"
down_revision: str | Sequence[str] | None = ("7c3f1e2a4b10", "c3d4e5f60718")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
