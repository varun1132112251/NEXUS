"""add reusable routine templates

Revision ID: 9a1b2c3d4e51
Revises: 8f9a1b2c3d40
"""

from alembic import op
import sqlalchemy as sa

revision = "9a1b2c3d4e51"
down_revision = "8f9a1b2c3d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routine_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("habit_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_id"], ["targets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_routine_templates_user_id", "routine_templates", ["user_id"])
    op.create_index("ix_routine_templates_weekday", "routine_templates", ["weekday"])


def downgrade() -> None:
    op.drop_index("ix_routine_templates_weekday", table_name="routine_templates")
    op.drop_index("ix_routine_templates_user_id", table_name="routine_templates")
    op.drop_table("routine_templates")
