from datetime import UTC, datetime

from app.core.auth_session_constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.models.auth_session import AuthSession
from app.services.mfa_service import mfa_service

ORIGIN = "http://localhost:3000"
PASSWORD = "Password1"


def _post(client, path: str, body: dict | None = None):
    headers = {"Origin": ORIGIN}
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    if csrf:
        headers[CSRF_HEADER_NAME] = csrf
    return client.post(path, json=body, headers=headers)


def _login_pending(client, user) -> dict:
    response = _post(
        client,
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _enroll(client, user, monkeypatch) -> tuple[str, list[str]]:
    monkeypatch.setenv("AUTH_TESTING_AUTO_VERIFY_MFA", "false")
    now = 1_800_000_000
    monkeypatch.setattr("app.services.mfa_service.time.time", lambda: now)
    login = _login_pending(client, user)
    assert login == {
        "token_type": "cookie",
        "user": None,
        "mfa_required": True,
        "mfa_enrollment_required": True,
    }
    assert client.get("/api/v1/auth/me").status_code == 401
    setup = _post(client, "/api/v1/auth/mfa/setup")
    assert setup.status_code == 200
    assert setup.headers["cache-control"] == "no-store"
    secret = setup.json()["data"]["secret"]
    code = mfa_service._totp(secret, now // 30)
    confirmed = _post(client, "/api/v1/auth/mfa/confirm", {"code": code})
    assert confirmed.status_code == 200
    recovery_codes = confirmed.json()["data"]["recovery_codes"]
    assert len(recovery_codes) == 10
    assert client.get("/api/v1/auth/me").status_code == 200
    return code, recovery_codes


def test_new_user_must_enroll_and_secret_is_encrypted(
    client, user_factory, db_session, monkeypatch
) -> None:
    user = user_factory("mfa-enroll@example.com")
    _, recovery_codes = _enroll(client, user, monkeypatch)
    db_session.refresh(user)
    assert user.mfa_enabled_at is not None
    assert user.mfa_secret_ciphertext is not None
    assert user.mfa_secret_ciphertext.startswith(b"MFA1")
    assert all(code.encode() not in user.mfa_secret_ciphertext for code in recovery_codes)
    assert set(user.mfa_recovery_code_hashes or []).isdisjoint(recovery_codes)


def test_totp_cannot_be_replayed_across_sessions(
    client, user_factory, monkeypatch
) -> None:
    user = user_factory("mfa-replay@example.com")
    code, _ = _enroll(client, user, monkeypatch)
    assert _post(client, "/api/v1/auth/logout").status_code == 200
    login = _login_pending(client, user)
    assert login["mfa_enrollment_required"] is False
    replay = _post(client, "/api/v1/auth/mfa/verify", {"code": code})
    assert replay.status_code == 401
    assert replay.json()["message"] == "Invalid MFA code"


def test_recovery_code_is_single_use(client, user_factory, monkeypatch) -> None:
    user = user_factory("mfa-recovery@example.com")
    _, recovery_codes = _enroll(client, user, monkeypatch)
    recovery = recovery_codes[0]
    assert _post(client, "/api/v1/auth/logout").status_code == 200
    _login_pending(client, user)
    verified = _post(client, "/api/v1/auth/mfa/verify", {"code": recovery})
    assert verified.status_code == 200
    assert verified.json()["data"]["recovery_code_used"] is True
    assert _post(client, "/api/v1/auth/logout").status_code == 200
    _login_pending(client, user)
    reused = _post(client, "/api/v1/auth/mfa/verify", {"code": recovery})
    assert reused.status_code == 401


def test_five_invalid_codes_revoke_pending_session(
    client, user_factory, db_session, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_TESTING_AUTO_VERIFY_MFA", "false")
    user = user_factory("mfa-failures@example.com")
    secret = mfa_service.generate_secret()
    user.mfa_secret_ciphertext = mfa_service.encrypt_secret(secret, user_id=str(user.id))
    user.mfa_enabled_at = datetime.now(UTC)
    user.mfa_recovery_code_hashes = []
    db_session.commit()
    _login_pending(client, user)
    for _ in range(5):
        response = _post(client, "/api/v1/auth/mfa/verify", {"code": "000000"})
        assert response.status_code == 401
    session = (
        db_session.query(AuthSession)
        .filter(AuthSession.user_id == user.id)
        .order_by(AuthSession.created_at.desc())
        .first()
    )
    assert session is not None
    assert session.mfa_failed_attempts == 5
    assert session.revoked_at is not None
    assert client.get("/api/v1/auth/me").status_code == 401


def test_setup_is_idempotent_and_does_not_rotate_pending_secret(
    client, user_factory, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_TESTING_AUTO_VERIFY_MFA", "false")
    user = user_factory("mfa-idempotent@example.com")
    _login_pending(client, user)
    first = _post(client, "/api/v1/auth/mfa/setup")
    second = _post(client, "/api/v1/auth/mfa/setup")
    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["secret"] == second.json()["data"]["secret"]


def test_pending_session_can_logout_but_cannot_access_business_api(
    client, user_factory, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_TESTING_AUTO_VERIFY_MFA", "false")
    user = user_factory("mfa-pending-logout@example.com")
    _login_pending(client, user)
    assert client.get("/api/v1/projects").status_code == 401
    assert _post(client, "/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
