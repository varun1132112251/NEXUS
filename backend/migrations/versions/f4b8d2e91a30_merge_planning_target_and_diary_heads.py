"""merge planning-target and diary migration heads

Revision ID: f4b8d2e91a30
Revises: e27b4d91c603, c92f4a7b1e20
Create Date: 2026-10-03 15:25:00.000000
"""

from collections.abc import Sequence

revision: str = "f4b8d2e91a30"
down_revision: tuple[str, str] = ("e27b4d91c603", "c92f4a7b1e20")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
