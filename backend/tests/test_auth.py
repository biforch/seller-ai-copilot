def test_register_and_login(client):
    register = client.post(
        "/api/v1/auth/register",
        json={"email": "new-user@example.com", "password": "Password1"},
    )
    assert register.status_code == 200
    assert register.json()["code"] == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "new-user@example.com", "password": "Password1"},
    )
    assert login.status_code == 200
    data = login.json()["data"]
    assert data["access_token"]
    assert data["user"]["email"] == "new-user@example.com"


def test_register_rejects_weak_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )
    assert response.status_code == 422
    assert response.json()["message"] == "Validation Error"


def test_login_rejects_invalid_credentials(client, user_factory):
    user_factory("known@example.com")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "known@example.com", "password": "WrongPass1"},
    )
    assert response.status_code == 401
    assert response.json()["message"] == "Invalid email or password"
