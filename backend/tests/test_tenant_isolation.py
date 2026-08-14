from app.models.generation import Generation
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def test_user_cannot_create_product_in_other_users_project(
    client, tenant_bundle, auth_header, valid_listing_payload
):
    owner = tenant_bundle("owner")
    intruder = tenant_bundle("intruder")

    response = client.post(
        "/api/v1/products",
        headers=auth_header(intruder["user"]),
        json={
            "project_id": str(owner["project"].id),
            "name": "Stolen Product",
            "category": "Electronics",
        },
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Project not found"


def test_user_cannot_read_other_users_product(client, tenant_bundle, auth_header):
    owner = tenant_bundle("owner")
    intruder = tenant_bundle("intruder")

    response = client.get(
        f"/api/v1/products/{owner['product'].id}",
        headers=auth_header(intruder["user"]),
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Product not found"


def test_user_cannot_read_other_users_project(client, tenant_bundle, auth_header):
    owner = tenant_bundle("owner")
    intruder = tenant_bundle("intruder")

    response = client.get(
        f"/api/v1/projects/{owner['project'].id}",
        headers=auth_header(intruder["user"]),
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Project not found"


def test_user_cannot_read_other_users_generations_via_product_detail(
    client,
    tenant_bundle,
    auth_header,
    auth_and_idempotency,
    isolated_client_ip,
    db_session,
    valid_listing_payload,
    monkeypatch,
):
    owner = tenant_bundle("owner")
    intruder = tenant_bundle("intruder")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 100
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    created = client.post(
        "/api/v1/generate/listing",
        headers={
            **auth_and_idempotency(owner["user"]),
            **isolated_client_ip("10.88.1.1"),
        },
        json=valid_listing_payload(owner["project"].id),
    )
    assert created.status_code == 200

    leaked = client.get(
        f"/api/v1/products/{owner['product'].id}",
        headers=auth_header(intruder["user"]),
    )
    assert leaked.status_code == 404

    generation_count = (
        db_session.query(Generation)
        .filter(Generation.user_id == owner["user"].id)
        .count()
    )
    assert generation_count >= 1


def test_cannot_bypass_with_own_product_and_foreign_project(
    client,
    tenant_bundle,
    auth_header,
    auth_and_idempotency,
    isolated_client_ip,
    valid_listing_payload,
    monkeypatch,
):
    owner = tenant_bundle("owner")
    intruder = tenant_bundle("intruder")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 50
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    before_products = client.get(
        "/api/v1/products",
        headers=auth_header(intruder["user"]),
    ).json()["data"]["items"]
    before_count = len(before_products)

    response = client.post(
        "/api/v1/generate/listing",
        headers={
            **auth_and_idempotency(intruder["user"]),
            **isolated_client_ip("10.88.1.2"),
        },
        json=valid_listing_payload(
            intruder["project"].id,
            product_id=str(owner["product"].id),
        ),
    )
    assert response.status_code == 200

    after_products = client.get(
        "/api/v1/products",
        headers=auth_header(intruder["user"]),
    ).json()["data"]["items"]
    assert len(after_products) == before_count + 1
    assert response.json()["data"]["product_id"] != str(owner["product"].id)


def test_missing_and_foreign_resources_share_not_found_message(
    client, tenant_bundle, auth_header
):
    intruder = tenant_bundle("intruder")
    headers = auth_header(intruder["user"])

    missing = client.get(
        "/api/v1/products/00000000-0000-4000-8000-000000000099",
        headers=headers,
    )
    assert missing.status_code == 404

    foreign = client.get(
        f"/api/v1/projects/{tenant_bundle('secret')['project'].id}",
        headers=headers,
    )
    assert foreign.status_code == 404
    assert foreign.json()["message"] == "Project not found"
