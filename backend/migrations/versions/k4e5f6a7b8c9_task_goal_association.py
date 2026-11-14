"""link tasks to long-term ambition goals

Revision ID: k4e5f6a7b8c9
Revises: k3d4e5f6a7b8
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "k4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "k3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("ambition_goal_id", sa.Uuid(), nullable=True))
    op.create_index("ix_tasks_ambition_goal_id", "tasks", ["ambition_goal_id"])
    op.create_foreign_key(
        "fk_tasks_ambition_goal_user", "tasks", "ambition_goals",
        ["ambition_goal_id", "user_id"], ["id", "user_id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM tasks WHERE ambition_goal_id IS NOT NULL)")).scalar_one():
        raise RuntimeError("Cannot downgrade task goal association while tasks reference ambition goals.")
    op.drop_constraint("fk_tasks_ambition_goal_user", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_ambition_goal_id", table_name="tasks")
    op.drop_column("tasks", "ambition_goal_id")
