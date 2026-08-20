import uuid

from app.services.openai import OpenAIService
from tests.conftest import TEST_ORIGIN
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def test_auth_register_rate_limit_on_real_route(client, isolated_client_ip):
    headers = {**isolated_client_ip("10.20.30.40"), "Origin": TEST_ORIGIN}
    responses = []

    for index in range(11):
        response = client.post(
            "/api/v1/auth/register",
            headers=headers,
            json={
                "email": f"rate-limit-auth-{index}@example.com",
                "password": "Password1",
            },
        )
        responses.append(response)

    success_count = sum(1 for response in responses if response.status_code == 200)
    limited = [response for response in responses if response.status_code == 429]

    assert success_count >= 10
    assert limited, "Expected auth register route to enforce 10/minute limit"
    payload = limited[0].json()
    assert payload["code"] == 429
    assert payload["message"] == "Too Many Requests"
    assert "detail" in payload


def test_generate_listing_rate_limit_on_real_route(
    client,
    tenant_bundle,
    auth_header,
    valid_listing_payload,
    isolated_client_ip,
    monkeypatch,
):
    tenant = tenant_bundle("rate-limit-generate")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 1
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    headers = {
        **auth_header(tenant["user"]),
        **isolated_client_ip("10.20.30.50"),
    }

    responses = []
    for _ in range(21):
        req_headers = {**headers, "Idempotency-Key": str(uuid.uuid4())}
        responses.append(
            client.post(
                "/api/v1/generate/listing",
                headers=req_headers,
                json=valid_listing_payload(tenant["project"].id),
            )
        )

    success_count = sum(1 for response in responses if response.status_code == 200)
    limited = [response for response in responses if response.status_code == 429]

    assert success_count >= 20
    assert limited, "Expected generate/listing route to enforce 20/hour limit"
    payload = limited[0].json()
    assert payload["code"] == 429
    assert payload["message"] == "Too Many Requests"
