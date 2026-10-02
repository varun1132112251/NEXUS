from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class DiaryEntry(Base):
    __tablename__ = "diary_entries"
    __table_args__ = (UniqueConstraint("user_id", "entry_date", name="uq_diary_entries_user_date"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    accomplishments: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_went_badly: Mapped[str | None] = mapped_column(Text, nullable=True)
    learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    feelings: Mapped[str | None] = mapped_column(Text, nullable=True)
    distractions: Mapped[str | None] = mapped_column(Text, nullable=True)
    tomorrow_changes: Mapped[str | None] = mapped_column(Text, nullable=True)
    free_writing: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("CURRENT_TIMESTAMP"))
