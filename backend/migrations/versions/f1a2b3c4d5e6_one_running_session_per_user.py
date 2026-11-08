"""enforce one running time session per user

Revision ID: f1a2b3c4d5e6
Revises: a6b1c2d3e4f5
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "a6b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This intentionally fails without deleting data if a user already has
    # multiple running sessions. Resolve those rows explicitly before retrying.
    op.create_index(
        "uq_time_sessions_one_running_per_user",
        "time_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_time_sessions_one_running_per_user",
        table_name="time_sessions",
    )
