
import uuid

import pytest

from app.core.config import settings
from app.core.rate_limit import rate_limit_key
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


class _FakeRequest:
    def __init__(self, headers: dict[str, str], client_host: str = "127.0.0.1"):
        self.headers = headers
        self.client = type("Client", (), {"host": client_host})()


def test_testing_environment_uses_x_test_client_ip(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "testing")
    request = _FakeRequest({"X-Test-Client-IP": "10.0.0.99"}, client_host="127.0.0.1")
    assert rate_limit_key(request) == "10.0.0.99"


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_non_testing_environment_ignores_x_test_client_ip(monkeypatch, environment):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    request = _FakeRequest({"X-Test-Client-IP": "10.0.0.99"}, client_host="203.0.113.10")
    assert rate_limit_key(request) != "10.0.0.99"
    assert rate_limit_key(request) == "203.0.113.10"


def test_production_cannot_bypass_rate_limit_with_x_test_client_ip(
    client,
    tenant_bundle,
    auth_header,
    valid_listing_payload,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(
        "app.core.rate_limit.get_remote_address",
        lambda request: "203.0.113.55",
    )

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 1
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    tenant = tenant_bundle("prod-rate-limit")
    base_headers = auth_header(tenant["user"])

    first_ip = {**base_headers, "X-Test-Client-IP": "10.99.1.1"}
    second_ip = {**base_headers, "X-Test-Client-IP": "10.99.2.2"}

    for _ in range(20):
        response = client.post(
            "/api/v1/generate/listing",
            headers={**first_ip, "Idempotency-Key": str(uuid.uuid4())},
            json=valid_listing_payload(tenant["project"].id),
        )
        assert response.status_code == 200

    blocked = client.post(
        "/api/v1/generate/listing",
        headers={**second_ip, "Idempotency-Key": str(uuid.uuid4())},
        json=valid_listing_payload(tenant["project"].id),
    )
    assert blocked.status_code == 429
