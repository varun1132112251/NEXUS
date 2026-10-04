"""repair semantic metric types for existing targets

Revision ID: 8f9a1b2c3d40
Revises: 7e8f9a1b2c31
"""

from alembic import op
import sqlalchemy as sa

revision = "8f9a1b2c3d40"
down_revision = "7e8f9a1b2c31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    targets = sa.table(
        "targets",
        sa.column("title", sa.String()),
        sa.column("metric_type", sa.String()),
    )

    # Repair existing targets created before semantic metric enforcement.
    op.execute(
        targets.update()
        .where(sa.func.lower(targets.c.title).like("%dsa%"))
        .values(metric_type="problems_solved")
    )
    op.execute(
        targets.update()
        .where(sa.func.lower(targets.c.title).like("%problem%"))
        .values(metric_type="problems_solved")
    )
    op.execute(
        targets.update()
        .where(sa.func.lower(targets.c.title).like("%read%book%"))
        .values(metric_type="books_completed")
    )
    op.execute(
        targets.update()
        .where(
            sa.and_(
                sa.func.lower(targets.c.title).like("%english%"),
                sa.func.lower(targets.c.title).like("%session%"),
            )
        )
        .values(metric_type="sessions_completed")
    )
    op.execute(
        targets.update()
        .where(
            sa.and_(
                sa.func.lower(targets.c.title).like("%gate%"),
                sa.func.lower(targets.c.title).like("%revision%"),
            )
        )
        .values(metric_type="topics_revised")
    )
    op.execute(
        targets.update()
        .where(
            sa.and_(
                sa.func.lower(targets.c.title).like("%gate%"),
                sa.func.lower(targets.c.title).like("%question%"),
            )
        )
        .values(metric_type="questions_solved")
    )
    op.execute(
        targets.update()
        .where(
            sa.and_(
                sa.func.lower(targets.c.title).like("%nexus%"),
                sa.func.lower(targets.c.title).like("%complete%"),
            )
        )
        .values(metric_type="milestones_completed")
    )


def downgrade() -> None:
    pass
