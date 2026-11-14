from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TimeSessionSegment(Base):
    """An active stopwatch interval; paused time has no open segment."""

    __tablename__ = "time_session_segments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["time_session_id", "user_id"],
            ["time_sessions.id", "time_sessions.user_id"],
            ondelete="CASCADE",
            name="fk_time_session_segments_session_user",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="ck_time_session_segments_range"),
        Index("uq_time_session_segments_one_open", "time_session_id", unique=True, postgresql_where=text("ended_at IS NULL")),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    time_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))
