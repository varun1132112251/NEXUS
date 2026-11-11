"""Device activity ingestion with revocation serialized on the source row."""

from datetime import datetime
import hmac
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.activity_source import ActivitySource, credential_digest, verify_credential


class InvalidDeviceCredential(ValueError):
    pass


class DuplicateActivityEvent(ValueError):
    def __init__(self, event: ActivityEvent):
        self.event = event
        super().__init__("Event already ingested")


def ingest_device_event(
    db: Session,
    *,
    credential: str,
    external_event_id: str,
    event_type: str,
    occurred_at: datetime,
    payload: dict[str, Any] | None = None,
    confidence: float = 0.0,
) -> ActivityEvent:
    """Validate an active source and insert one idempotent event transactionally.

    The source row lock is held through the caller's transaction. Revocation
    first means ingestion sees a revoked row and fails; ingestion first means
    its event transaction commits before revocation can complete.
    """
    try:
        digest = credential_digest(credential)
    except RuntimeError as exc:
        raise InvalidDeviceCredential("Device credential verification is unavailable") from exc
    source = db.execute(
        select(ActivitySource)
        .where(ActivitySource.credential_hash == digest, ActivitySource.revoked_at.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if source is None or not verify_credential(credential, source.credential_hash) or not hmac.compare_digest(digest, source.credential_hash):
        raise InvalidDeviceCredential("Invalid or revoked device credential")
    event_row = ActivityEvent(
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        confidence=confidence,
        payload=payload or {},
    )
    db.add(event_row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ActivityEvent).where(
                ActivityEvent.source_id == source.id,
                ActivityEvent.external_event_id == external_event_id,
            )
        )
        if existing is not None:
            raise DuplicateActivityEvent(existing)
        raise
    return event_row
