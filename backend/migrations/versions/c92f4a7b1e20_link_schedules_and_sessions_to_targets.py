"""link schedules and sessions to targets

Revision ID: c92f4a7b1e20
Revises: b41d7e2a91f0
Create Date: 2026-10-03 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c92f4a7b1e20"
down_revision: str | None = "b41d7e2a91f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedule_items",
        sa.Column("target_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_schedule_items_target_id", "schedule_items", ["target_id"])
    op.create_foreign_key(
        "fk_schedule_items_target_id_targets",
        "schedule_items",
        "targets",
        ["target_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "time_sessions",
        sa.Column("target_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_time_sessions_target_id", "time_sessions", ["target_id"])
    op.create_foreign_key(
        "fk_time_sessions_target_id_targets",
        "time_sessions",
        "targets",
        ["target_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_time_sessions_target_id_targets", "time_sessions", type_="foreignkey")
    op.drop_index("ix_time_sessions_target_id", table_name="time_sessions")
    op.drop_column("time_sessions", "target_id")

    op.drop_constraint("fk_schedule_items_target_id_targets", "schedule_items", type_="foreignkey")
    op.drop_index("ix_schedule_items_target_id", table_name="schedule_items")
    op.drop_column("schedule_items", "target_id")
