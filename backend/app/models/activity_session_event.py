from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActivitySessionEvent(Base):
    """User-scoped provenance edge from an interpreted session to raw evidence."""

    __tablename__ = "activity_session_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["activity_session_id", "user_id"],
            ["activity_sessions.id", "activity_sessions.user_id"],
            ondelete="CASCADE",
            name="fk_activity_session_events_session_user",
        ),
        ForeignKeyConstraint(
            ["activity_event_id", "user_id"],
            ["activity_events.id", "activity_events.user_id"],
            ondelete="RESTRICT",
            name="fk_activity_session_events_event_user",
        ),
    )

    activity_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    activity_event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="evidence", server_default="evidence")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))
