import hashlib
import hmac

import pytest

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.paddle_billing_service import checkout_user_signature, verify_paddle_signature


def test_checkout_user_signature_is_stable_and_user_bound(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-jwt-secret-key-minimum-32-characters")
    first = checkout_user_signature("00000000-0000-0000-0000-000000000001")
    assert first == checkout_user_signature("00000000-0000-0000-0000-000000000001")
    assert first != checkout_user_signature("00000000-0000-0000-0000-000000000002")


def test_verify_paddle_signature_accepts_valid_payload(monkeypatch):
    secret = "pdl_ntfset_test"
    timestamp = 1_800_000_000
    body = b'{"event_id":"evt_1"}'
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b":" + body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(settings, "PADDLE_WEBHOOK_SECRET", secret)
    monkeypatch.setattr("app.services.paddle_billing_service.time.time", lambda: timestamp)
    verify_paddle_signature(body, f"ts={timestamp};h1={digest}")


def test_verify_paddle_signature_rejects_tampering(monkeypatch):
    timestamp = 1_800_000_000
    monkeypatch.setattr(settings, "PADDLE_WEBHOOK_SECRET", "pdl_ntfset_test")
    monkeypatch.setattr("app.services.paddle_billing_service.time.time", lambda: timestamp)
    with pytest.raises(AppException) as error:
        verify_paddle_signature(b"tampered", f"ts={timestamp};h1={'0' * 64}")
    assert error.value.error_code == "BILLING_SIGNATURE_INVALID"
