from datetime import timedelta
import pytest
from app.core.config import settings
from app.core.security import create_access_token, create_auth_ticket, create_verification_code, decode_access_token, decode_auth_ticket, hash_one_time_token


def test_codes_have_unambiguous_alphabet():
    allowed = set("23456789ABCDEFGHJKLMNPQRSTUVWXYZ")
    for _ in range(100):
        code = create_verification_code()
        assert len(code) == 6 and set(code) <= allowed


def test_hmac_hash_is_contextual_and_keyed(monkeypatch):
    context = "person@example.com:email_verification"
    value = hash_one_time_token("ABC234", context=context)
    assert value == hash_one_time_token("ABC234", context=context)
    assert value != hash_one_time_token("abc234", context=context)
    assert value != hash_one_time_token("ABC234", context="another@example.com:email_verification")
    monkeypatch.setattr(settings, "jwt_secret_key", settings.jwt_secret_key + "-rotated")
    assert value != hash_one_time_token("ABC234", context=context)


def test_access_token_auth_version():
    payload = decode_access_token(create_access_token("user-123", auth_version=7))
    assert payload["sub"] == "user-123" and payload["ver"] == 7


def test_expired_access_token_rejected():
    with pytest.raises(ValueError):
        decode_access_token(create_access_token("user-123", expires_delta=timedelta(seconds=-1)))


def test_auth_ticket_is_purpose_bound():
    ticket = create_auth_ticket(purpose="account_setup", email="person@example.com")
    assert decode_auth_ticket(ticket, "account_setup")["email"] == "person@example.com"
    with pytest.raises(ValueError):
        decode_auth_ticket(ticket, "password_recovery")


def test_auth_ticket_tampering_rejected():
    ticket = create_auth_ticket(purpose="account_setup", email="person@example.com")
    altered = ticket[:-1] + ("A" if ticket[-1] != "A" else "B")
    with pytest.raises(ValueError):
        decode_auth_ticket(altered, "account_setup")
