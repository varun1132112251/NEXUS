from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.activity_event import ActivityEvent
from app.models.activity_source import ActivitySource, issue_credential
from app.models.user import User
from app.schemas.activity_source import (
    ActivityDeviceEvent,
    ActivityEventIngested,
    ActivityEventRead,
    ActivitySourceCreate,
    ActivitySourceRead,
    ActivitySourceRegistered,
)
from app.services.activity_sources import DuplicateActivityEvent, InvalidDeviceCredential, ingest_device_event
from app.services.activity_review import draft_from_application_end

router = APIRouter(prefix="/activity-sources", tags=["activity-sources"])


@router.post("", response_model=ActivitySourceRegistered, status_code=status.HTTP_201_CREATED)
def register_source(
    payload: ActivitySourceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        source, credential = issue_credential(
            db, user_id=user.id, name=payload.name, source_type=payload.source_type
        )
        db.commit()
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Device registration is unavailable.") from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A device with this name is already registered.") from exc
    db.refresh(source)
    return ActivitySourceRegistered(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        created_at=source.created_at,
        revoked_at=source.revoked_at,
        credential=credential,
    )


@router.get("", response_model=list[ActivitySourceRead])
def list_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list(
        db.scalars(
            select(ActivitySource)
            .where(ActivitySource.user_id == user.id)
            .order_by(ActivitySource.created_at.desc(), ActivitySource.id)
        ).all()
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_source(
    source_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = db.scalar(
        select(ActivitySource)
        .where(ActivitySource.id == source_id, ActivitySource.user_id == user.id)
        .with_for_update()
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Activity source not found.")
    if source.revoked_at is None:
        source.revoked_at = datetime.now(UTC)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/events", response_model=ActivityEventIngested)
def ingest_event(
    payload: ActivityDeviceEvent,
    response: Response,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(status_code=401, detail="Device credential required.", headers={"WWW-Authenticate": "Bearer"})
    try:
        event = ingest_device_event(
            db,
            credential=credential,
            external_event_id=payload.external_event_id,
            event_type=payload.event_type,
            occurred_at=payload.occurred_at,
            confidence=payload.confidence,
            payload=payload.payload,
        )
        draft_from_application_end(db, event)
        db.commit()
        db.refresh(event)
        return ActivityEventIngested(event=event, duplicate=False)
    except DuplicateActivityEvent as exc:
        response.status_code = status.HTTP_200_OK
        draft_from_application_end(db, exc.event)
        db.commit()
        db.refresh(exc.event)
        return ActivityEventIngested(event=exc.event, duplicate=True)
    except InvalidDeviceCredential as exc:
        db.rollback()
        if "unavailable" in str(exc).lower():
            raise HTTPException(status_code=503, detail="Device credential verification is unavailable.") from exc
        raise HTTPException(status_code=401, detail="Invalid or revoked device credential.", headers={"WWW-Authenticate": "Bearer"}) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Event could not be ingested.") from exc
