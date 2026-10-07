from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.google_auth import verify_google_id_token
from app.core.mailer import send_auth_email
from app.core.security import (
    create_access_token,
    create_auth_ticket,
    create_one_time_token,
    decode_access_token,
    decode_auth_ticket,
    hash_one_time_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.auth_identity import AuthIdentity
from app.models.auth_token import AuthToken
from app.models.user import User
from app.schemas.auth import (
    AccountSetupRequest,
    EmailStartRequest,
    EmailVerifyRequest,
    GoogleAuthResponse,
    GoogleLoginRequest,
    LoginRequest,
    PasswordResetCompleteRequest,
    PasswordResetStartRequest,
    Token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated.", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
        user = db.get(User, UUID(subject)) if isinstance(subject, str) else None
    except (ValueError, TypeError):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.", headers={"WWW-Authenticate": "Bearer"})
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    identifier = payload.identifier
    user = db.scalar(select(User).where((User.username == identifier) | (User.email == identifier)))
    if user is None or not user.email_verified or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.", headers={"WWW-Authenticate": "Bearer"})
    return Token(access_token=create_access_token(user.id))


@router.post("/email/start", response_model=dict)
def start_email_verification(payload: EmailStartRequest, db: Session = Depends(get_db)) -> dict:
    email = payload.email
    existing = db.scalar(select(User).where(User.email == email))
    if existing and existing.email_verified:
        raise HTTPException(status_code=409, detail="An account already exists for this email. Sign in instead.")

    raw = create_one_time_token()[:6].upper()
    token = AuthToken(
        email=email,
        purpose="email_verification",
        token_hash=hash_one_time_token(raw),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    db.add(token)
    db.commit()
    send_auth_email(
        email,
        "Verify your NEXUS email",
        f"Your NEXUS verification code is: {raw[:6].upper()}\n\nThis code expires in 15 minutes.",
    )
    return {"message": "If this email can be used for authentication, a verification message has been sent."}


@router.post("/email/verify")
def verify_email(payload: EmailVerifyRequest, db: Session = Depends(get_db)):
    token = db.scalar(
        select(AuthToken)
        .where(
            AuthToken.email == payload.email,
            AuthToken.purpose == "email_verification",
            AuthToken.consumed_at.is_(None),
        )
        .order_by(AuthToken.created_at.desc())
    )
    if token is None or token.expires_at <= datetime.now(UTC) or token.token_hash != hash_one_time_token(payload.code):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")

    token.consumed_at = datetime.now(UTC)
    user = db.scalar(select(User).where(User.email == payload.email))
    if user:
        user.email_verified = True
        db.commit()
        return Token(access_token=create_access_token(user.id))

    db.commit()
    setup = create_auth_ticket(purpose="account_setup", email=payload.email)
    return {"setup_token": setup, "email": payload.email, "name": None}


@router.post("/google", response_model=GoogleAuthResponse)
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)) -> GoogleAuthResponse:
    try:
        info = verify_google_id_token(payload.credential)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Google authentication.") from exc

    subject = str(info["sub"])
    email = str(info["email"]).strip().lower()
    name = info.get("name")
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google",
            AuthIdentity.provider_subject == subject,
        )
    )
    if identity:
        user = db.get(User, identity.user_id)
        if user:
            return GoogleAuthResponse(requires_setup=False, access_token=create_access_token(user.id))

    user = db.scalar(select(User).where(User.email == email))
    if user:
        if not user.email_verified:
            user.email_verified = True
        identity = AuthIdentity(user_id=user.id, provider="google", provider_subject=subject)
        db.add(identity)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        return GoogleAuthResponse(requires_setup=False, access_token=create_access_token(user.id))

    setup = create_auth_ticket(
        purpose="account_setup",
        email=email,
        name=name,
        provider="google",
        provider_subject=subject,
    )
    return GoogleAuthResponse(requires_setup=True, setup_token=setup, email=email, name=name)


@router.post("/setup", response_model=Token)
def complete_account_setup(payload: AccountSetupRequest, db: Session = Depends(get_db)) -> Token:
    try:
        ticket = decode_auth_ticket(payload.setup_token, "account_setup")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired setup session.") from exc

    email = str(ticket["email"]).strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account already exists for this email.")

    user = User(
        username=payload.username.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        email_verified=True,
    )
    db.add(user)
    try:
        db.flush()
        provider = ticket.get("provider")
        subject = ticket.get("provider_subject")
        if provider and subject:
            db.add(AuthIdentity(user_id=user.id, provider=provider, provider_subject=subject))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is already in use.") from exc
    db.refresh(user)
    return Token(access_token=create_access_token(user.id))


@router.post("/password-reset/start", response_model=dict)
def start_password_reset(payload: PasswordResetStartRequest, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == payload.email, User.email_verified.is_(True)))
    if user:
        raw = create_one_time_token()[:6].upper()
        db.add(
            AuthToken(
                user_id=user.id,
                email=user.email,
                purpose="password_reset",
                token_hash=hash_one_time_token(raw),
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        db.commit()
        send_auth_email(
            user.email,
            "Reset your NEXUS password",
            f"Your NEXUS password reset code is: {raw[:6].upper()}\n\nThis code expires in 15 minutes.",
        )
    return {"message": "If an account exists for this email, a reset message has been sent."}


@router.post("/password-reset/complete", response_model=Token)
def complete_password_reset(payload: PasswordResetCompleteRequest, db: Session = Depends(get_db)) -> Token:
    token = db.scalar(
        select(AuthToken)
        .where(
            AuthToken.email == payload.email,
            AuthToken.purpose == "password_reset",
            AuthToken.consumed_at.is_(None),
        )
        .order_by(AuthToken.created_at.desc())
    )
    if token is None or token.expires_at <= datetime.now(UTC) or token.token_hash != hash_one_time_token(payload.reset_token):
        raise HTTPException(status_code=400, detail="Invalid or expired reset code.")
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid reset request.")
    user.password_hash = hash_password(payload.password)
    token.consumed_at = datetime.now(UTC)
    db.commit()
    return Token(access_token=create_access_token(user.id))
