from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActivitySessionLineage(Base):
    """Immutable edge recording which sessions a split/merge derived from."""

    __tablename__ = "activity_session_lineage"
    __table_args__ = (
        ForeignKeyConstraint(["parent_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], ondelete="RESTRICT", name="fk_activity_session_lineage_parent_user"),
        ForeignKeyConstraint(["child_session_id", "user_id"], ["activity_sessions.id", "activity_sessions.user_id"], ondelete="RESTRICT", name="fk_activity_session_lineage_child_user"),
    )

    parent_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    child_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), server_default=text("CURRENT_TIMESTAMP"))
