"""PostgreSQL API regression tests for target deletion and historical activity links."""

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.orm import sessionmaker

from app.api.v1.routes.auth import get_current_user
from app.api.v1.routes import targets as target_routes
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ActivityGoalContribution, ActivitySession, Target, User


POSTGRES_TEST_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_TEST_URL, reason="requires a dedicated disposable PostgreSQL database")


@pytest.fixture
def pg_sessions():
    admin = create_engine(POSTGRES_TEST_URL)
    schema = f"target_delete_{uuid4().hex}"
    with admin.begin() as connection:
        assert connection.dialect.name == "postgresql"
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(POSTGRES_TEST_URL)

    @event.listens_for(engine, "connect")
    def set_search_path(connection, _record):
        cursor = connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def make_user(db, name: str) -> User:
    user = User(id=uuid4(), username=f"{name}-{uuid4()}", email=f"{uuid4()}@example.test", password_hash="unused")
    db.add(user)
    db.flush()
    return user


def make_target(db, user: User, title: str) -> Target:
    target = Target(user_id=user.id, title=title, month=date(2026, 11, 1), metric_type="count", target_value=10)
    db.add(target)
    db.flush()
    return target


def make_activity(db, user: User, target: Target | None, title: str) -> ActivitySession:
    started = datetime(2026, 11, 14, 9, tzinfo=UTC)
    activity = ActivitySession(
        user_id=user.id, target_id=target.id if target else None, title=title,
        started_at=started, ended_at=started + timedelta(minutes=10), duration_seconds=600,
        status="confirmed", source_kind="manual",
    )
    db.add(activity)
    db.flush()
    return activity


def target_client(user: User, sessions) -> TestClient:
    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def target_client_for_session(user: User, db, *, raise_server_exceptions: bool = True) -> TestClient:
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_target_delete_removes_only_unreferenced_target(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "owner")
        target = make_target(db, user, "Unused target")
        db.commit()
        client = target_client(user, pg_sessions)
        try:
            response = client.delete(f"/api/v1/targets/{target.id}")
        finally:
            app.dependency_overrides.clear()
        assert response.status_code == 204
        assert db.scalar(select(Target.id).where(Target.id == target.id)) is None


def test_activity_references_return_api_conflict_and_preserve_history_and_ownership(pg_sessions):
    with pg_sessions() as db:
        owner = make_user(db, "owner")
        other = make_user(db, "other")
        target = make_target(db, owner, "Historical target")
        unrelated_target = make_target(db, other, "Other user's target")
        first = make_activity(db, owner, target, "First historical session")
        second = make_activity(db, owner, target, "Second historical session")
        unrelated_activity = make_activity(db, other, unrelated_target, "Other user's session")
        db.commit()
        client = target_client(owner, pg_sessions)
        try:
            response = client.delete(f"/api/v1/targets/{target.id}")
            other_client = target_client(other, pg_sessions)
            foreign_response = other_client.delete(f"/api/v1/targets/{target.id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409
        assert "historical activity" in response.json()["detail"]
        assert foreign_response.status_code == 404
        db.expire_all()
        assert db.get(Target, target.id) is not None
        assert db.get(Target, unrelated_target.id) is not None
        assert db.get(ActivitySession, first.id).target_id == target.id
        assert db.get(ActivitySession, second.id).target_id == target.id
        assert db.get(ActivitySession, unrelated_activity.id).target_id == unrelated_target.id


def test_contribution_reference_returns_conflict_without_leaking_integrity_error(pg_sessions):
    with pg_sessions() as db:
        user = make_user(db, "contributor")
        target = make_target(db, user, "Contributed target")
        activity = make_activity(db, user, target, "Contributed session")
        contribution = ActivityGoalContribution(
            user_id=user.id, activity_session_id=activity.id, target_id=target.id,
            goal_id=None, contribution_type="metric", contribution_value=Decimal(1), unit="count",
        )
        db.add(contribution)
        db.commit()
        client = target_client(user, pg_sessions)
        try:
            response = client.delete(f"/api/v1/targets/{target.id}")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 409
        db.expire_all()
        assert db.get(Target, target.id) is not None
        assert db.get(ActivitySession, activity.id).target_id == target.id
        assert db.get(ActivityGoalContribution, contribution.id) is not None


@pytest.mark.parametrize("reference_kind,expected_constraint,expected_sqlstate", [
    ("activity_session", "fk_activity_sessions_target_user", "23001"),
    ("contribution", "fk_activity_goal_contributions_target_user", "23503"),
])
def test_expected_postgres_target_fk_returns_409_and_session_recovers(
    pg_sessions, monkeypatch, reference_kind, expected_constraint, expected_sqlstate,
):
    with pg_sessions() as db:
        user = make_user(db, f"expected-{reference_kind}")
        target = make_target(db, user, "Referenced target")
        if reference_kind == "activity_session":
            # Match K6's deployed ON DELETE RESTRICT definition exactly.
            db.execute(text("ALTER TABLE activity_sessions DROP CONSTRAINT fk_activity_sessions_target_user"))
            db.execute(text("""
                ALTER TABLE activity_sessions ADD CONSTRAINT fk_activity_sessions_target_user
                FOREIGN KEY (target_id, user_id) REFERENCES targets(id, user_id) ON DELETE RESTRICT
            """))
        activity = make_activity(db, user, target if reference_kind == "activity_session" else None, "Reference")
        contribution = None
        if reference_kind == "contribution":
            contribution = ActivityGoalContribution(
                user_id=user.id, activity_session_id=activity.id, target_id=target.id,
                goal_id=None, contribution_type="metric", contribution_value=Decimal(1), unit="count",
            )
            db.add(contribution)
        db.commit()

        diagnostics = []
        def capture_error(context):
            original = context.original_exception
            diagnostics.append((getattr(original, "sqlstate", None), getattr(getattr(original, "diag", None), "constraint_name", None)))
        event.listen(db.get_bind(), "handle_error", capture_error)
        monkeypatch.setattr(target_routes, "unlink_owned_references", lambda *_args: None)
        client = target_client_for_session(user, db)
        try:
            response = client.delete(f"/api/v1/targets/{target.id}")
        finally:
            app.dependency_overrides.clear()
            event.remove(db.get_bind(), "handle_error", capture_error)

        assert response.status_code == 409
        assert (expected_sqlstate, expected_constraint) in diagnostics
        assert not db.in_transaction()
        assert db.get(Target, target.id) is not None
        assert db.get(ActivitySession, activity.id) is not None
        if reference_kind == "activity_session":
            assert db.get(ActivitySession, activity.id).target_id == target.id
        else:
            assert db.get(ActivitySession, activity.id).target_id is None
            assert db.get(ActivityGoalContribution, contribution.id) is not None
        db.execute(update(Target).where(Target.id == target.id).values(description="recovered after rollback"))
        db.commit()
        assert db.get(Target, target.id).description == "recovered after rollback"


@pytest.mark.parametrize("failure_kind,sqlstate,constraint_name", [
    ("foreign_key", "23503", "fk_test_unrelated_target_ref"),
    ("unique", "23505", "uq_test_target_delete_marker"),
    ("check", "23514", "ck_test_target_delete_positive"),
])
def test_unrelated_integrity_errors_propagate_after_rollback_and_session_recovers(
    pg_sessions, failure_kind, sqlstate, constraint_name,
):
    with pg_sessions() as db:
        user = make_user(db, f"unrelated-{failure_kind}")
        target = make_target(db, user, "Unrelated constraint target")
        if failure_kind == "foreign_key":
            db.execute(text("""
                CREATE TABLE target_delete_fk_guard (
                  id integer PRIMARY KEY,
                  target_id uuid NOT NULL,
                  CONSTRAINT fk_test_unrelated_target_ref FOREIGN KEY (target_id)
                        REFERENCES targets(id)
                )
            """))
            db.execute(text("INSERT INTO target_delete_fk_guard (id, target_id) VALUES (1, :id)"), {"id": target.id})
        elif failure_kind == "unique":
            db.execute(text("CREATE TABLE target_delete_unique_guard (marker text CONSTRAINT uq_test_target_delete_marker UNIQUE)"))
            db.execute(text("INSERT INTO target_delete_unique_guard (marker) VALUES ('occupied')"))
            db.execute(text("""
                CREATE FUNCTION target_delete_unique_guard_fn() RETURNS trigger AS $$
                BEGIN
                  INSERT INTO target_delete_unique_guard (marker) VALUES ('occupied');
                  RETURN OLD;
                END; $$ LANGUAGE plpgsql
            """))
            db.execute(text("CREATE TRIGGER target_delete_unique_guard BEFORE DELETE ON targets FOR EACH ROW EXECUTE FUNCTION target_delete_unique_guard_fn()"))
        else:
            db.execute(text("CREATE TABLE target_delete_check_guard (value integer CONSTRAINT ck_test_target_delete_positive CHECK (value > 0))"))
            db.execute(text("""
                CREATE FUNCTION target_delete_check_guard_fn() RETURNS trigger AS $$
                BEGIN
                  INSERT INTO target_delete_check_guard (value) VALUES (-1);
                  RETURN OLD;
                END; $$ LANGUAGE plpgsql
            """))
            db.execute(text("CREATE TRIGGER target_delete_check_guard BEFORE DELETE ON targets FOR EACH ROW EXECUTE FUNCTION target_delete_check_guard_fn()"))
        db.commit()

        diagnostics = []
        def capture_error(context):
            original = context.original_exception
            diagnostics.append((getattr(original, "sqlstate", None), getattr(getattr(original, "diag", None), "constraint_name", None)))
        event.listen(db.get_bind(), "handle_error", capture_error)
        client = target_client_for_session(user, db, raise_server_exceptions=False)
        try:
            response = client.delete(f"/api/v1/targets/{target.id}")
        finally:
            app.dependency_overrides.clear()
            event.remove(db.get_bind(), "handle_error", capture_error)

        assert response.status_code == 500
        assert (sqlstate, constraint_name) in diagnostics
        assert not db.in_transaction()
        assert db.get(Target, target.id) is not None
        db.execute(update(Target).where(Target.id == target.id).values(description="recovered after rollback"))
        db.commit()
        assert db.get(Target, target.id).description == "recovered after rollback"
