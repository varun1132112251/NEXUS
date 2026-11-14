"""retain routine template identity on schedule occurrences

Revision ID: k5f6a7b8c9d0
Revises: k4e5f6a7b8c9
"""

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "k5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "k4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    invalid = bind.execute(sa.text("""
        SELECT
          EXISTS (SELECT 1 FROM routine_templates r JOIN habits h ON h.id=r.habit_id WHERE r.user_id<>h.user_id) OR
          EXISTS (SELECT 1 FROM routine_templates r JOIN tasks t ON t.id=r.task_id WHERE r.user_id<>t.user_id) OR
          EXISTS (SELECT 1 FROM routine_templates r JOIN projects p ON p.id=r.project_id WHERE r.user_id<>p.user_id) OR
          EXISTS (SELECT 1 FROM routine_templates r JOIN targets t ON t.id=r.target_id WHERE r.user_id<>t.user_id)
    """)).scalar_one()
    if invalid:
        raise RuntimeError("Cannot constrain routine ownership: cross-user routine references exist. Correct them explicitly before retrying.")

    op.create_unique_constraint("uq_routine_templates_id_user_id", "routine_templates", ["id", "user_id"])
    for constraint, field, parent in (
        ("fk_routine_templates_habit_user", "habit_id", "habits"),
        ("fk_routine_templates_task_user", "task_id", "tasks"),
        ("fk_routine_templates_project_user", "project_id", "projects"),
        ("fk_routine_templates_target_user", "target_id", "targets"),
    ):
        op.create_foreign_key(constraint, "routine_templates", parent, [field, "user_id"], ["id", "user_id"], ondelete="RESTRICT")

    op.add_column("schedule_items", sa.Column("routine_template_id", sa.Uuid(), nullable=True))
    op.create_index("ix_schedule_items_routine_template_id", "schedule_items", ["routine_template_id"])
    op.create_foreign_key("fk_schedule_items_routine_user", "schedule_items", "routine_templates", ["routine_template_id", "user_id"], ["id", "user_id"], ondelete="RESTRICT")
    op.create_index("uq_schedule_routine_occurrence", "schedule_items", ["routine_template_id", "scheduled_date"], unique=True, postgresql_where=sa.text("routine_template_id IS NOT NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM schedule_items WHERE routine_template_id IS NOT NULL)")).scalar_one():
        raise RuntimeError("Cannot downgrade routine occurrence identity while generated schedule rows reference templates.")
    op.drop_index("uq_schedule_routine_occurrence", table_name="schedule_items")
    op.drop_constraint("fk_schedule_items_routine_user", "schedule_items", type_="foreignkey")
    op.drop_index("ix_schedule_items_routine_template_id", table_name="schedule_items")
    op.drop_column("schedule_items", "routine_template_id")
    for constraint in ("fk_routine_templates_target_user", "fk_routine_templates_project_user", "fk_routine_templates_task_user", "fk_routine_templates_habit_user"):
        op.drop_constraint(constraint, "routine_templates", type_="foreignkey")
    op.drop_constraint("uq_routine_templates_id_user_id", "routine_templates", type_="unique")
