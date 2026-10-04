"""prevent duplicate activity reviews per time session

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
"""
from alembic import op

revision = "b2c3d4e5f607"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_index("uq_activity_records_time_session_id", "activity_records", ["time_session_id"], unique=True, postgresql_where="time_session_id IS NOT NULL")

def downgrade() -> None:
    op.drop_index("uq_activity_records_time_session_id", table_name="activity_records")
