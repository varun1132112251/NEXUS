from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    Uuid,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActivityCorrection(Base):
    """An immutable record of a field correction and its before/after values."""

    __tablename__ = "activity_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_session_id", "user_id"],
            ["activity_sessions.id", "activity_sessions.user_id"],
            ondelete="RESTRICT",
            name="fk_activity_corrections_session_user",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    activity_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_value: Mapped[object] = mapped_column(JSONB, nullable=False)
    new_value: Mapped[object] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    def __setattr__(self, key: str, value: object) -> None:
        if key in {"user_id", "activity_session_id", "field_name", "previous_value", "new_value", "reason"} and key in self.__dict__:
            raise AttributeError("ActivityCorrection records are immutable")
        super().__setattr__(key, value)


event.listen(
    ActivityCorrection.__table__,
    "after_create",
    DDL("""
    CREATE FUNCTION nexus_reject_activity_correction_mutation() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION 'activity correction history is immutable';
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_activity_corrections_immutable
      BEFORE UPDATE OR DELETE ON activity_corrections
      FOR EACH ROW EXECUTE FUNCTION nexus_reject_activity_correction_mutation();
    """),
)

event.listen(
    ActivityCorrection.__table__,
    "before_drop",
    DDL("DROP FUNCTION IF EXISTS nexus_reject_activity_correction_mutation();"),
)
