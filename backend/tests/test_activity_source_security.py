from datetime import UTC, datetime
from uuid import uuid4

from app.models.activity_source import ActivitySource
from app.models.activity_source import credential_digest, verify_credential


def test_revoked_source_is_not_active_for_credential(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "activity_source_hmac_key", "k" * 32)
    class Result:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return Result()

    db = FakeDb()
    assert ActivitySource.active_for_credential(db, "digest") is None
    sql = str(db.statement)
    assert "revoked_at IS NULL" in sql


def test_activity_correction_retains_json_values():
    from app.models.activity_correction import ActivityCorrection

    row = ActivityCorrection(
        user_id=uuid4(), activity_session_id=uuid4(), field_name="title",
        previous_value={"v": 1}, new_value={"v": 2}, created_at=datetime.now(UTC),
    )
    assert row.previous_value == {"v": 1}
    assert row.new_value == {"v": 2}


def test_device_credential_is_keyed_and_verified_in_constant_time(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "activity_source_hmac_key", "k" * 32)
    credential = "high-entropy-device-token"
    digest = credential_digest(credential)
    assert digest != credential
    assert verify_credential(credential, digest)
    assert not verify_credential("wrong-token", digest)
