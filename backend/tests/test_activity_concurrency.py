from datetime import date
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.api.v1.routes.activity_records import increment_target_progress
from app.models.target import Target


class StatementCapture:
    def __init__(self) -> None:
        self.statement = None

    def execute(self, statement):
        self.statement = statement


def test_target_progress_uses_atomic_database_increment() -> None:
    target = Target(
        id=uuid4(),
        user_id=uuid4(),
        title="Solve DSA problems",
        month=date(2026, 11, 1),
        metric_type="problems_solved",
        target_value=100,
        current_value=12,
    )
    db = StatementCapture()

    increment_target_progress(db, target, target.user_id, 3)

    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "UPDATE targets SET current_value=(targets.current_value +" in sql
    assert "WHERE targets.id =" in sql
    assert "AND targets.user_id =" in sql
