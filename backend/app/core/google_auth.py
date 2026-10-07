from google.auth.transport import requests
from google.oauth2 import id_token

from app.core.config import settings


def verify_google_id_token(credential: str) -> dict:
    if not settings.google_client_id:
        raise ValueError("Google authentication is not configured.")
    info = id_token.verify_oauth2_token(
        credential,
        requests.Request(),
        settings.google_client_id,
    )
    if info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Invalid Google token issuer.")
    if not info.get("sub") or not info.get("email"):
        raise ValueError("Google token is missing required identity claims.")
    if info.get("email_verified") is not True:
        raise ValueError("Google email is not verified.")
    return info
