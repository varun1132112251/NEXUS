"""add long-term goal and direct activity associations to planner rows

Revision ID: k6a7b8c9d0e1
Revises: k5f6a7b8c9d0
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "k6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "k5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schedule_items", sa.Column("ambition_goal_id", sa.Uuid(), nullable=True))
    op.create_index("ix_schedule_items_ambition_goal_id", "schedule_items", ["ambition_goal_id"])
    op.create_foreign_key("fk_schedule_items_ambition_goal_user", "schedule_items", "ambition_goals", ["ambition_goal_id", "user_id"], ["id", "user_id"], ondelete="RESTRICT")

    op.add_column("activity_sessions", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.create_index("ix_activity_sessions_target_id", "activity_sessions", ["target_id"])
    op.create_foreign_key("fk_activity_sessions_target_user", "activity_sessions", "targets", ["target_id", "user_id"], ["id", "user_id"], ondelete="RESTRICT")


def downgrade() -> None:
    bind = op.get_bind()
    unsafe = bind.execute(sa.text("""
        SELECT
          EXISTS (SELECT 1 FROM schedule_items WHERE ambition_goal_id IS NOT NULL) OR
          EXISTS (SELECT 1 FROM activity_sessions WHERE target_id IS NOT NULL)
    """)).scalar_one()
    if unsafe:
        raise RuntimeError("Cannot downgrade planner goal/activity associations while user links exist.")
    op.drop_constraint("fk_activity_sessions_target_user", "activity_sessions", type_="foreignkey")
    op.drop_index("ix_activity_sessions_target_id", table_name="activity_sessions")
    op.drop_column("activity_sessions", "target_id")
    op.drop_constraint("fk_schedule_items_ambition_goal_user", "schedule_items", type_="foreignkey")
    op.drop_index("ix_schedule_items_ambition_goal_id", table_name="schedule_items")
    op.drop_column("schedule_items", "ambition_goal_id")
