def test_generate_listing_rejects_blank_name(client, tenant_bundle, auth_and_idempotency):
    tenant = tenant_bundle("validation-user")
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(tenant["user"]),
        json={
            "project_id": str(tenant["project"].id),
            "name": "   ",
            "category": "Electronics",
        },
    )
    assert response.status_code == 422


def test_generate_listing_rejects_invalid_project_uuid(client, tenant_bundle, auth_and_idempotency):
    tenant = tenant_bundle("validation-user-2")
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(tenant["user"]),
        json={
            "project_id": "not-a-uuid",
            "name": "Valid Name",
            "category": "Electronics",
        },
    )
    assert response.status_code == 422


def test_create_project_rejects_oversized_description(client, tenant_bundle, auth_header):
    tenant = tenant_bundle("validation-user-3")
    response = client.post(
        "/api/v1/projects",
        headers=auth_header(tenant["user"]),
        json={
            "name": "Valid Project",
            "description": "x" * 1001,
        },
    )
    assert response.status_code == 422


def test_create_product_rejects_too_many_advantages(client, tenant_bundle, auth_header):
    tenant = tenant_bundle("validation-user-4")
    response = client.post(
        "/api/v1/products",
        headers=auth_header(tenant["user"]),
        json={
            "project_id": str(tenant["project"].id),
            "name": "Valid Product",
            "advantages": [f"advantage-{index}" for index in range(21)],
        },
    )
    assert response.status_code == 422


def test_create_product_accepts_max_length_fields(client, tenant_bundle, auth_header):
    tenant = tenant_bundle("validation-user-5")
    response = client.post(
        "/api/v1/products",
        headers=auth_header(tenant["user"]),
        json={
            "project_id": str(tenant["project"].id),
            "name": "n" * 255,
            "category": "c" * 100,
            "target_customer": "t" * 255,
            "advantages": ["a" * 200] * 20,
        },
    )
    assert response.status_code == 200
    assert response.json()["code"] == 201
