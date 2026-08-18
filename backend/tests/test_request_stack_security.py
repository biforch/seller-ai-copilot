"""FastAPI/Starlette request-stack security regressions."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.main import app

CANARY_TOKEN = "canary.bearer.token.must-not-leak"


@pytest.fixture
def api_client() -> TestClient:
    return TestClient(app)


def test_health_endpoint_responds(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["code"] == 200


def test_json_body_validation_returns_422(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "Password1"},
    )
    assert response.status_code == 422
    assert response.json()["message"] == "Validation Error"


def test_extra_fields_are_rejected() -> None:
    class StrictPayload(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str

    isolated = FastAPI()

    @isolated.post("/strict")
    def accept(payload: StrictPayload) -> dict[str, str]:
        return {"name": payload.name}

    client = TestClient(isolated)
    response = client.post("/strict", json={"name": "seller", "unexpected": "x"})
    assert response.status_code == 422


def test_unauthenticated_projects_request_uses_existing_contract(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/projects")
    assert response.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    }


def test_invalid_bearer_token_does_not_echo_canary(api_client: TestClient) -> None:
    response = api_client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {CANARY_TOKEN}"},
    )
    assert response.status_code == 401
    assert CANARY_TOKEN not in response.text


def test_amazon_error_handler_sanitizes_unknown_codes(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/amazon/oauth/start?marketplace=US")
    assert response.status_code in {
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_405_METHOD_NOT_ALLOWED,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    }
    assert "Traceback" not in response.text
