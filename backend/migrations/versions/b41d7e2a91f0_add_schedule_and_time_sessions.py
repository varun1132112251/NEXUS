"""add schedule and time sessions

Revision ID: b41d7e2a91f0
Revises: 8c2f4a91d7b3
Create Date: 2026-10-02 13:30:00.000000
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "b41d7e2a91f0"
down_revision: str | None = "8c2f4a91d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table("schedule_items",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True), sa.Column("habit_id", sa.Uuid(), nullable=True), sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=False), sa.Column("start_at", sa.DateTime(timezone=True), nullable=False), sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="3", nullable=False), sa.Column("status", sa.String(32), server_default="planned", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    for column in ("user_id", "task_id", "habit_id", "project_id", "scheduled_date"): op.create_index(f"ix_schedule_items_{column}", "schedule_items", [column])

    op.create_table("time_sessions",
        sa.Column("id", sa.Uuid(), nullable=False), sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_item_id", sa.Uuid(), nullable=True), sa.Column("task_id", sa.Uuid(), nullable=True), sa.Column("habit_id", sa.Uuid(), nullable=True), sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True), sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), server_default="running", nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["schedule_item_id"], ["schedule_items.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    for column in ("user_id", "schedule_item_id", "task_id", "habit_id", "project_id"): op.create_index(f"ix_time_sessions_{column}", "time_sessions", [column])

def downgrade() -> None:
    for column in ("project_id", "habit_id", "task_id", "schedule_item_id", "user_id"): op.drop_index(f"ix_time_sessions_{column}", table_name="time_sessions")
    op.drop_table("time_sessions")
    for column in ("scheduled_date", "project_id", "habit_id", "task_id", "user_id"): op.drop_index(f"ix_schedule_items_{column}", table_name="schedule_items")
    op.drop_table("schedule_items")
