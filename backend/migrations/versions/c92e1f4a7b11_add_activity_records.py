"""add activity records

Revision ID: c92e1f4a7b11
Revises: b41d7e2a91f0
"""

from alembic import op
import sqlalchemy as sa


revision = "c92e1f4a7b11"
down_revision = "b41d7e2a91f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("time_session_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("habit_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("activity_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["time_session_id"], ["time_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("user_id", "time_session_id", "task_id", "habit_id", "project_id", "activity_type", "recorded_at"):
        op.create_index(f"ix_activity_records_{column}", "activity_records", [column], unique=False)


def downgrade() -> None:
    for column in ("recorded_at", "activity_type", "project_id", "habit_id", "task_id", "time_session_id", "user_id"):
        op.drop_index(f"ix_activity_records_{column}", table_name="activity_records")
    op.drop_table("activity_records")
