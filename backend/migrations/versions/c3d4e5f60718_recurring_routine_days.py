"""change routine templates from one weekday to recurring weekdays

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f60718"
down_revision = "b2c3d4e5f607"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("routine_templates", sa.Column("weekdays", sa.JSON(), nullable=True))
    op.execute("UPDATE routine_templates SET weekdays = json_build_array(weekday)")
    op.alter_column("routine_templates", "weekdays", nullable=False)
    op.drop_column("routine_templates", "weekday")

def downgrade() -> None:
    op.add_column("routine_templates", sa.Column("weekday", sa.Integer(), nullable=True))
    op.execute("UPDATE routine_templates SET weekday = (weekdays->>0)::integer")
    op.alter_column("routine_templates", "weekday", nullable=False)
    op.drop_column("routine_templates", "weekdays")
