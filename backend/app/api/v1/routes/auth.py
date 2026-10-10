import logging
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.google_auth import verify_google_id_token
from app.core.mailer import send_auth_email
from app.core.security import (
    create_access_token,
    create_auth_ticket,
    create_one_time_token,
    create_verification_code,
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
    PasswordRecoverySessionRequest,
    PasswordResetCompleteRequest,
    PasswordResetStartRequest,
    PasswordResetVerifyRequest,
    Token,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

CODE_TTL = timedelta(minutes=15)
RATE_WINDOW = timedelta(minutes=15)
RECOVERY_SESSION_TTL = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 8
MAX_LOGIN_FAILURES = 8
MAX_EMAIL_SENDS = 3


def _auth_version(user: User) -> int:
    return int(getattr(user, "auth_version", None) or 1)


def _context(email: str, purpose: str) -> str:
    return email + ":" + purpose


def _lock_rate_bucket(db: Session, purpose: str, key: str) -> None:
    execute = getattr(db, "execute", None)
    if execute is not None:
        execute(text("SELECT pg_advisory_xact_lock(hashtext(:bucket))"), {"bucket": purpose + ":" + key})


def _new_marker(email: str, purpose: str, expires_at: datetime) -> AuthToken:
    return AuthToken(
        email=email,
        purpose=purpose,
        token_hash=hash_one_time_token(create_one_time_token(), context=_context(email, purpose)),
        expires_at=expires_at,
    )


def _count_active_recent(db: Session, email: str, purpose: str, cutoff: datetime) -> int:
    result = db.scalar(
        select(func.count(AuthToken.id)).where(
            AuthToken.email == email,
            AuthToken.purpose == purpose,
            AuthToken.created_at >= cutoff,
            AuthToken.consumed_at.is_(None),
        )
    )
    return int(result or 0)


def _enforce_send_limit(db: Session, email: str, purpose: str) -> None:
    now = datetime.now(UTC)
    _lock_rate_bucket(db, purpose, email)
    if _count_active_recent(db, email, purpose, now - RATE_WINDOW) >= MAX_EMAIL_SENDS:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before requesting another email.",
            headers={"Retry-After": "900"},
        )
    db.add(_new_marker(email, purpose, now + RATE_WINDOW))
    db.commit()


def _latest_token(db: Session, email: str, purpose: str) -> AuthToken | None:
    # created_at can tie for rows inserted in one PostgreSQL transaction. UUID
    # provides a deterministic tie-breaker; both columns are indexed/cheap.
    return db.scalar(
        select(AuthToken)
        .where(AuthToken.email == email, AuthToken.purpose == purpose)
        .order_by(AuthToken.created_at.desc(), AuthToken.id.desc())
        .limit(1)
        .with_for_update()
    )


def _record_login_failure(db: Session, email: str) -> None:
    db.add(_new_marker(email, "login_failed", datetime.now(UTC) + RATE_WINDOW))
    db.commit()


def _check_login_limit(db: Session, email: str) -> None:
    _lock_rate_bucket(db, "login_failed", email)
    if _count_active_recent(db, email, "login_failed", datetime.now(UTC) - RATE_WINDOW) >= MAX_LOGIN_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Wait 15 minutes and try again.",
            headers={"Retry-After": "900"},
        )


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated.", headers={"WWW-Authenticate": "Bearer"})
    payload = None
    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")
        user = db.get(User, UUID(subject)) if isinstance(subject, str) else None
    except (ValueError, TypeError):
        user = None
    if user is not None and payload.get("ver", 1) != _auth_version(user):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authentication token.", headers={"WWW-Authenticate": "Bearer"})
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    identifier = payload.identifier
    user = db.scalar(
        select(User).where((User.username == identifier) | (User.email == identifier.lower()))
    )
    # Rate-limit on the supplied identifier, not a resolved account email. This
    # prevents alternate identifiers from bypassing the same login bucket and
    # avoids exposing whether an account exists through the limit response.
    rate_key = identifier.strip().lower()
    _check_login_limit(db, rate_key)
    if user is None or not user.email_verified or not verify_password(payload.password, user.password_hash):
        _record_login_failure(db, rate_key)
        raise HTTPException(status_code=401, detail="Invalid credentials.", headers={"WWW-Authenticate": "Bearer"})
    return Token(access_token=create_access_token(user.id, auth_version=_auth_version(user)))


@router.post("/email/start", response_model=dict)
def start_email_verification(payload: EmailStartRequest, db: Session = Depends(get_db)) -> dict:
    email = str(payload.email)
    existing = db.scalar(select(User).where(User.email == email))
    if existing and existing.email_verified:
        raise HTTPException(status_code=409, detail="An account already exists for this email. Sign in instead.")
    _enforce_send_limit(db, email, "email_start_limit")
    now = datetime.now(UTC)
    code = create_verification_code()
    token = AuthToken(
        email=email,
        purpose="email_verification",
        token_hash=hash_one_time_token(code, context=_context(email, "email_verification")),
        expires_at=now + CODE_TTL,
    )
    db.add(token)
    db.commit()
    try:
        send_auth_email(
            email,
            "Verify your email address — NEXUS",
            "Hello,\n\nWelcome to NEXUS — your personalized operating system for goals, routines, and productivity.\n\nTo complete your registration, enter the verification code below on the NEXUS registration page.\n\n"
            + f"Your NEXUS verification code is: {code}\n\nThis code expires in 15 minutes.\n\nIf you did not request this code, you can safely ignore this email. Never share your verification code with anyone.",
        )
    except Exception as exc:
        logger.exception("Failed to deliver NEXUS email verification.")
        token.consumed_at = datetime.now(UTC)
        db.commit()
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable. Please try again later.") from exc
    return {"message": "If this email can be used for authentication, a verification message has been sent."}


@router.post("/email/verify")
def verify_email(payload: EmailVerifyRequest, db: Session = Depends(get_db)):
    email = str(payload.email)
    token = _latest_token(db, email, "email_verification")
    now = datetime.now(UTC)
    valid = (
        token is not None and token.consumed_at is None and token.expires_at > now
        and compare_digest(
            token.token_hash,
            hash_one_time_token(payload.code, context=_context(email, "email_verification")),
        )
    )
    if not valid:
        if token is not None and token.consumed_at is None and token.expires_at > now:
            token.failed_attempts = int(getattr(token, "failed_attempts", 0) or 0) + 1
            if token.failed_attempts >= MAX_CODE_ATTEMPTS:
                token.consumed_at = now
            db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
    token.consumed_at = now
    user = db.scalar(select(User).where(User.email == email))
    if user:
        user.email_verified = True
        db.commit()
        return Token(access_token=create_access_token(user.id, auth_version=_auth_version(user)))
    db.commit()
    ticket = create_auth_ticket(purpose="account_setup", email=email)
    return {"setup_token": ticket, "email": email, "name": None}


@router.post("/google", response_model=GoogleAuthResponse)
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)) -> GoogleAuthResponse:
    try:
        info = verify_google_id_token(payload.credential)
    except Exception as exc:
        logger.info("Rejected Google sign-in: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid Google authentication.") from exc
    subject = str(info["sub"])
    email = str(info["email"]).strip().lower()
    name = info.get("name")
    identity = db.scalar(select(AuthIdentity).where(
        AuthIdentity.provider == "google",
        AuthIdentity.provider_subject == subject,
    ))
    if identity:
        user = db.get(User, identity.user_id)
        if user:
            return GoogleAuthResponse(requires_setup=False, access_token=create_access_token(user.id, auth_version=_auth_version(user)))
    user = db.scalar(select(User).where(User.email == email))
    if user:
        if not user.email_verified:
            raise HTTPException(status_code=409, detail="Verify this email with NEXUS before linking Google sign-in.")
        identity = AuthIdentity(user_id=user.id, provider="google", provider_subject=subject)
        user.email_verified = True
        db.add(identity)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            identity = db.scalar(select(AuthIdentity).where(
                AuthIdentity.provider == "google",
                AuthIdentity.provider_subject == subject,
            ))
            if identity is None or identity.user_id != user.id:
                raise HTTPException(status_code=409, detail="Unable to link this Google identity.") from exc
        return GoogleAuthResponse(requires_setup=False, access_token=create_access_token(user.id, auth_version=_auth_version(user)))
    ticket = create_auth_ticket(
        purpose="account_setup", email=email, name=name,
        provider="google", provider_subject=subject,
    )
    return GoogleAuthResponse(requires_setup=True, setup_token=ticket, email=email, name=name)


@router.post("/setup", response_model=Token)
def complete_account_setup(payload: AccountSetupRequest, db: Session = Depends(get_db)) -> Token:
    try:
        ticket = decode_auth_ticket(payload.setup_token, "account_setup")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired setup session.") from exc
    email = str(ticket["email"]).strip().lower()
    provider = ticket.get("provider")
    if provider != "google" and not payload.password:
        raise HTTPException(status_code=422, detail="A password is required for email/password accounts.")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account already exists for this email.")
    password = payload.password or create_one_time_token()
    user = User(
        username=payload.username.strip(), email=email,
        password_hash=hash_password(password), email_verified=True,
    )
    db.add(user)
    try:
        db.flush()
        subject = ticket.get("provider_subject")
        if provider and subject:
            db.add(AuthIdentity(user_id=user.id, provider=provider, provider_subject=subject))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is already in use.") from exc
    db.refresh(user)
    return Token(access_token=create_access_token(user.id, auth_version=_auth_version(user)))


@router.post("/password-reset/start", response_model=dict)
def start_password_reset(payload: PasswordResetStartRequest, db: Session = Depends(get_db)) -> dict:
    email = str(payload.email)
    _enforce_send_limit(db, email, "password_reset_start_limit")
    user = db.scalar(select(User).where(User.email == email, User.email_verified.is_(True)))
    if user:
        code = create_verification_code()
        now = datetime.now(UTC)
        token = AuthToken(
            user_id=user.id, email=user.email, purpose="password_reset",
            token_hash=hash_one_time_token(code, context=_context(email, "password_reset")),
            expires_at=now + CODE_TTL,
        )
        db.add(token)
        db.commit()
        try:
            send_auth_email(
                user.email, "Reset your NEXUS password — NEXUS",
                "Hello,\n\nWe received a request to recover your NEXUS account. Use the code below to continue with password recovery.\n\n"
                + f"Your NEXUS password reset code is: {code}\n\nThis code expires in 15 minutes.\n\nIf you did not request a password reset, you can safely ignore this email. Never share your recovery code with anyone.",
            )
        except Exception:
            logger.exception("Failed to deliver NEXUS password-reset email.")
            token.consumed_at = datetime.now(UTC)
            db.commit()
    return {"message": "If an account exists for this email, a reset message has been sent."}


@router.post("/password-reset/verify", response_model=dict)
def verify_password_reset(payload: PasswordResetVerifyRequest, db: Session = Depends(get_db)) -> dict:
    email = str(payload.email)
    token = _latest_token(db, email, "password_reset")
    now = datetime.now(UTC)
    valid = (
        token is not None and token.consumed_at is None and token.expires_at > now
        and compare_digest(
            token.token_hash,
            hash_one_time_token(payload.reset_token, context=_context(email, "password_reset")),
        )
    )
    if not valid:
        if token is not None and token.consumed_at is None and token.expires_at > now:
            token.failed_attempts = int(getattr(token, "failed_attempts", 0) or 0) + 1
            if token.failed_attempts >= MAX_CODE_ATTEMPTS:
                token.consumed_at = now
            db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired recovery code.")
    user = db.get(User, token.user_id)
    if user is None or not user.email_verified:
        token.consumed_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired recovery code.")
    token.consumed_at = now
    recovery_session = create_one_time_token()
    db.add(AuthToken(
        user_id=user.id, email=user.email, purpose="password_reset_session",
        token_hash=hash_one_time_token(recovery_session, context=_context(email, "password_reset_session")),
        expires_at=now + RECOVERY_SESSION_TTL,
    ))
    db.commit()
    return {"recovery_session": recovery_session, "expires_in_seconds": int(RECOVERY_SESSION_TTL.total_seconds())}


def _consume_recovery_session(payload: PasswordRecoverySessionRequest, db: Session) -> User:
    email = str(payload.email)
    token = _latest_token(db, email, "password_reset_session")
    now = datetime.now(UTC)
    valid = (
        token is not None and token.consumed_at is None and token.expires_at > now
        and compare_digest(
            token.token_hash,
            hash_one_time_token(payload.recovery_session, context=_context(email, "password_reset_session")),
        )
    )
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired recovery session.")
    user = db.get(User, token.user_id)
    if user is None or not user.email_verified:
        token.consumed_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired recovery session.")
    token.consumed_at = now
    return user


@router.post("/password-reset/complete", response_model=Token)
def complete_password_reset(payload: PasswordResetCompleteRequest, db: Session = Depends(get_db)) -> Token:
    user = _consume_recovery_session(payload, db)
    user.password_hash = hash_password(payload.password)
    user.auth_version = _auth_version(user) + 1
    db.commit()
    return Token(access_token=create_access_token(user.id, auth_version=_auth_version(user)))


@router.post("/password-reset/continue", response_model=Token)
def continue_after_password_recovery(payload: PasswordRecoverySessionRequest, db: Session = Depends(get_db)) -> Token:
    user = _consume_recovery_session(payload, db)
    db.commit()
    return Token(access_token=create_access_token(user.id, auth_version=_auth_version(user)))
