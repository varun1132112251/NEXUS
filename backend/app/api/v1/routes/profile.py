import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_profile import UserProfile
from app.schemas.user_profile import UserProfileRead, UserProfileUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserProfileRead)
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfile:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    if (
        not profile.onboarding_completed
        and profile.name
        and profile.college
        and profile.degree
        and profile.branch
        and profile.year
        and profile.semester
        and profile.availability
        and profile.preferences
    ):
        profile.onboarding_completed = True
        db.commit()
        db.refresh(profile)
        logger.info("Auto-recovered completed legacy profile for user_id=%s", current_user.id)
    logger.info("Profile read for user_id=%s onboarding_completed=%s", current_user.id, profile.onboarding_completed)
    return profile


@router.put("", response_model=UserProfileRead)
def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfile:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == current_user.id))
    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.add(profile)

    logger.info("Profile update for user_id=%s onboarding_completed=%s", current_user.id, payload.onboarding_completed)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile
