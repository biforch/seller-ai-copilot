TEST_ORIGIN = "http://localhost:3000"


def test_register_and_login(client):
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "new-user@example.com", "password": "Password1!abc"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert register.status_code == 200
    assert register.json()["code"] == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "new-user@example.com", "password": "Password1!abc"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert login.status_code == 200
    data = login.json()["data"]
    assert "access_token" not in data
    assert data["token_type"] == "cookie"
    assert data["user"]["email"] == "new-user@example.com"


def test_register_rejects_weak_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert response.status_code == 422
    assert response.json()["message"] == "Validation Error"


def test_register_enforces_password_length_and_character_classes(client):
    invalid_passwords = (
        "Short1!",
        "lowercase123!",
        "UPPERCASE123!",
        "NoNumbersHere!",
        "NoSpecial1234",
        "Aa1!" + "x" * 125,
    )
    for index, password in enumerate(invalid_passwords):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": f"invalid-{index}@example.com", "password": password},
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 422


def test_login_rejects_invalid_credentials(client, user_factory):
    user_factory("known@example.com")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "known@example.com", "password": "WrongPass1"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert response.status_code == 401
    assert response.json()["message"] == "Invalid email or password"


def test_unknown_and_known_accounts_share_public_failure_contract(client, user_factory):
    user_factory("known-contract@example.com")
    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword!234"},
            headers={"Origin": TEST_ORIGIN},
        )
        for email in ("known-contract@example.com", "unknown-contract@example.com")
    ]
    assert [(response.status_code, response.json()) for response in responses] == [
        (401, responses[0].json()),
        (401, responses[0].json()),
    ]


def test_login_locks_account_after_repeated_failures(client, user_factory, db_session):
    user = user_factory("locked@example.com", password="Password1!abc")
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "WrongPassword!234"},
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password1!abc"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert locked.status_code == 401
    assert locked.json()["message"] == "Invalid email or password"
    db_session.refresh(user)
    assert user.failed_login_attempts == 5
    assert user.locked_until is not None


def test_successful_login_clears_failure_state(client, user_factory, db_session):
    user = user_factory("retry@example.com", password="Password1!abc")
    failed = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "WrongPassword!234"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert failed.status_code == 401
    success = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Password1!abc"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert success.status_code == 200
    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
