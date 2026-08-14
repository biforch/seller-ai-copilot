"""REST API tests for listing import, current, and version history."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from fastapi import status
from sqlalchemy import event

from app.core.exceptions import IDEMPOTENCY_CONFLICT, LISTING_NOT_FOUND
from app.models.listing_version import ListingVersion
from app.models.product import Product
from app.schemas.listing import ListingSnapshot
from app.services.listing_version import import_listing_version, list_listing_versions
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def _version_count_for_product(db_session, product_id) -> int:
    return (
        db_session.query(ListingVersion)
        .filter(ListingVersion.product_id == product_id)
        .count()
    )


def _run_list_listing_versions_with_sql_capture(engine, db_session, tenant) -> list[str]:
    product_id = tenant["product"].id
    user_id = tenant["user"].id
    db_session.expunge_all()

    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        list_listing_versions(
            db_session,
            product_id=product_id,
            current_user_id=user_id,
            page=1,
            page_size=20,
        )
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
    return statements


def _assert_three_list_versions_selects(statements: list[str]) -> None:
    selects = [statement for statement in statements if statement.lstrip().lower().startswith("select")]
    assert len(selects) == 3
    lowered = [statement.lower() for statement in selects]
    assert any("from products" in statement for statement in lowered)
    assert any("count(" in statement and "listing_versions" in statement for statement in lowered)
    assert any(
        "from listing_versions" in statement and "order by" in statement and "limit" in statement
        for statement in lowered
    )


def _import_url(product_id) -> str:
    return f"/api/v1/products/{product_id}/listing/import"


def _current_url(product_id) -> str:
    return f"/api/v1/products/{product_id}/listing/current"


def _versions_url(product_id) -> str:
    return f"/api/v1/products/{product_id}/listing/versions"


def _import_body(**overrides) -> dict:
    body = {
        "title": VALID_LISTING_OUTPUT["title"],
        "bullets": list(VALID_LISTING_OUTPUT["bullets"]),
        "description": VALID_LISTING_OUTPUT["description"],
        "backend_keywords": list(VALID_LISTING_OUTPUT["keywords"]),
    }
    body.update(overrides)
    return body


def _import_headers(auth_header, idempotency_header, user, key: str | None = None) -> dict[str, str]:
    return {
        **auth_header(user),
        **idempotency_header(key),
    }


def _snapshot(**overrides) -> ListingSnapshot:
    return ListingSnapshot.model_validate(_import_body(**overrides))


def _assert_422_error_body(response) -> None:
    body = response.json()
    assert body["code"] == 422
    assert body["message"]
    serialized = json.dumps(body).lower()
    assert "request_hash" not in serialized
    assert "traceback" not in serialized
    assert "select " not in serialized


def _assert_no_internal_fields(payload: dict) -> None:
    serialized = json.dumps(payload)
    assert "operation_idempotency_key" not in serialized
    assert "request_hash" not in serialized


def test_import_unauthenticated_returns_403(client, tenant_bundle):
    tenant = tenant_bundle("listing-api-unauth")
    response = client.post(
        _import_url(tenant["product"].id),
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json=_import_body(),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_import_missing_idempotency_key_returns_422(
    client, tenant_bundle, auth_header
):
    tenant = tenant_bundle("listing-api-no-idem")
    response = client.post(
        _import_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
        json=_import_body(),
    )
    assert response.status_code == 422
    _assert_422_error_body(response)


def test_import_invalid_idempotency_key_returns_422(
    client, tenant_bundle, auth_header
):
    tenant = tenant_bundle("listing-api-bad-idem")
    response = client.post(
        _import_url(tenant["product"].id),
        headers={**auth_header(tenant["user"]), "Idempotency-Key": "not-a-uuid"},
        json=_import_body(),
    )
    assert response.status_code == 422
    _assert_422_error_body(response)


def test_import_invalid_body_returns_422(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-bad-body")
    response = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json={"title": "Only Title"},
    )
    assert response.status_code == 422
    _assert_422_error_body(response)


def test_import_four_bullets_returns_422(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-4-bullets")
    body = _import_body()
    body["bullets"] = body["bullets"][:4]
    response = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=body,
    )
    assert response.status_code == 422
    _assert_422_error_body(response)


def test_import_five_bullets_returns_201(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-5-bullets")
    response = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["replay"] is False
    assert data["is_first"] is True
    assert len(data["version"]["bullets"]) == 5


def test_import_first_creates_v1_current(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-api-first")
    response = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["version"]["version_number"] == 1
    assert data["version"]["is_current"] is True
    assert data["is_first"] is True

    product = db_session.query(Product).filter(Product.id == tenant["product"].id).one()
    assert str(product.current_listing_version_id) == data["version"]["id"]


def test_import_same_key_same_payload_replays(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-replay")
    key = str(uuid.uuid4())
    headers = _import_headers(auth_header, idempotency_header, tenant["user"], key)
    first = client.post(_import_url(tenant["product"].id), headers=headers, json=_import_body())
    assert first.status_code == 201
    first_id = first.json()["data"]["version"]["id"]

    second = client.post(_import_url(tenant["product"].id), headers=headers, json=_import_body())
    assert second.status_code == 200
    second_data = second.json()["data"]
    assert second_data["replay"] is True
    assert second_data["is_first"] is True
    assert second_data["version"]["id"] == first_id


def test_import_replay_v2_returns_same_version(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-api-replay-v2")
    key1 = str(uuid.uuid4())
    key2 = str(uuid.uuid4())
    v1 = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"], key1),
        json=_import_body(),
    )
    assert v1.status_code == 201

    v2 = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"], key2),
        json=_import_body(title="Version Two Title For Import"),
    )
    assert v2.status_code == 201
    v2_id = v2.json()["data"]["version"]["id"]
    assert v2.json()["data"]["is_first"] is False

    replay = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"], key2),
        json=_import_body(title="Version Two Title For Import"),
    )
    assert replay.status_code == 200
    replay_data = replay.json()["data"]
    assert replay_data["replay"] is True
    assert replay_data["is_first"] is False
    assert replay_data["version"]["id"] == v2_id
    assert _version_count_for_product(db_session, tenant["product"].id) == 2


def test_import_replay_survives_product_platform_change(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-api-platform-replay")
    product = db_session.query(Product).filter(Product.id == tenant["product"].id).one()
    product.platform = "Amazon"
    db_session.commit()

    key = str(uuid.uuid4())
    body = _import_body()
    headers = _import_headers(auth_header, idempotency_header, tenant["user"], key)
    first = client.post(_import_url(product.id), headers=headers, json=body)
    assert first.status_code == 201
    first_data = first.json()["data"]
    first_id = first_data["version"]["id"]
    assert first_data["version"]["marketplace"] == "Amazon"

    product.platform = "Walmart"
    db_session.commit()

    replay = client.post(_import_url(product.id), headers=headers, json=body)
    assert replay.status_code == 200
    replay_data = replay.json()["data"]
    assert replay_data["replay"] is True
    assert replay_data["version"]["id"] == first_id
    assert replay_data["version"]["marketplace"] == "Amazon"
    assert _version_count_for_product(db_session, product.id) == 1
    db_session.refresh(product)
    assert str(product.current_listing_version_id) == first_id

    new_version = client.post(
        _import_url(product.id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(title="Walmart Platform Version"),
    )
    assert new_version.status_code == 201
    assert new_version.json()["data"]["version"]["marketplace"] == "Walmart"
    assert _version_count_for_product(db_session, product.id) == 2


def test_import_same_key_different_payload_conflicts(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-conflict")
    key = str(uuid.uuid4())
    headers = _import_headers(auth_header, idempotency_header, tenant["user"], key)
    first = client.post(_import_url(tenant["product"].id), headers=headers, json=_import_body())
    assert first.status_code == 201

    second = client.post(
        _import_url(tenant["product"].id),
        headers=headers,
        json=_import_body(title="Different Title For Conflict Test"),
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error_code"] == IDEMPOTENCY_CONFLICT


def test_import_second_key_creates_v2_with_parent(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-api-v2")
    first = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    v1_id = first.json()["data"]["version"]["id"]

    second = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(title="Version Two Title For Import"),
    )
    assert second.status_code == 201
    data = second.json()["data"]
    assert data["version"]["version_number"] == 2
    assert data["version"]["is_current"] is True
    assert data["version"]["parent_version_id"] == v1_id
    assert data["is_first"] is False

    product = db_session.query(Product).filter(Product.id == tenant["product"].id).one()
    assert str(product.current_listing_version_id) == data["version"]["id"]


def test_import_cross_tenant_product_returns_404(
    client, tenant_bundle, auth_header, idempotency_header
):
    owner = tenant_bundle("listing-api-owner")
    intruder = tenant_bundle("listing-api-intruder")
    response = client.post(
        _import_url(owner["product"].id),
        headers=_import_headers(auth_header, idempotency_header, intruder["user"]),
        json=_import_body(),
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Product not found"


def test_import_response_excludes_internal_fields(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-no-internal")
    response = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    assert response.status_code == 201
    _assert_no_internal_fields(response.json())


def test_import_uses_product_platform_as_marketplace(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-api-platform")
    product = db_session.query(Product).filter(Product.id == tenant["product"].id).one()
    product.platform = "Walmart"
    db_session.commit()

    response = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    assert response.status_code == 201
    assert response.json()["data"]["version"]["marketplace"] == "Walmart"


def test_current_without_listing_returns_404(
    client, tenant_bundle, auth_header
):
    tenant = tenant_bundle("listing-api-no-current")
    response = client.get(
        _current_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == LISTING_NOT_FOUND
    assert response.json()["message"] == "Current listing not found"


def test_current_with_listing_returns_200(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-current")
    imported = client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    assert imported.status_code == 201
    version_id = imported.json()["data"]["version"]["id"]

    response = client.get(
        _current_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"]["id"] == version_id
    assert data["version"]["is_current"] is True


def test_current_version_fields_are_complete(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-api-current-fields")
    client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    response = client.get(
        _current_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    version = response.json()["data"]["version"]
    expected_keys = {
        "id",
        "product_id",
        "version_number",
        "source",
        "title",
        "bullets",
        "description",
        "backend_keywords",
        "marketplace",
        "language",
        "generation_id",
        "parent_version_id",
        "created_by",
        "created_at",
        "is_current",
    }
    assert set(version.keys()) == expected_keys
    assert version["source"] == "manual"
    assert version["language"] == "en-US"


def test_current_cross_tenant_returns_404(client, tenant_bundle, auth_header):
    owner = tenant_bundle("listing-current-owner")
    intruder = tenant_bundle("listing-current-intruder")
    response = client.get(
        _current_url(owner["product"].id),
        headers=auth_header(intruder["user"]),
    )
    assert response.status_code == 404
    assert response.json()["message"] == "Product not found"


def test_current_excludes_internal_fields(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-current-no-internal")
    client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    response = client.get(
        _current_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    _assert_no_internal_fields(response.json())


def test_current_includes_score(
    client, tenant_bundle, auth_header, idempotency_header
):
    tenant = tenant_bundle("listing-current-score")
    client.post(
        _import_url(tenant["product"].id),
        headers=_import_headers(auth_header, idempotency_header, tenant["user"]),
        json=_import_body(),
    )
    response = client.get(
        _current_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    score = response.json()["data"]["score"]
    assert score is not None
    assert set(score.keys()) == {
        "overall",
        "title_seo",
        "keyword_coverage",
        "benefit_clarity",
        "conversion_potential",
    }


def test_versions_empty_history_returns_200(
    client, tenant_bundle, auth_header
):
    tenant = tenant_bundle("listing-versions-empty")
    response = client.get(
        _versions_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"] == []
    assert data["pagination"]["total"] == 0
    assert data["pagination"]["total_pages"] == 0


def test_versions_pagination_totals(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-versions-page")
    for index in range(3):
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=_snapshot(title=f"Paginated Title {index}"),
            idempotency_key=str(uuid.uuid4()),
            marketplace="Amazon",
        )

    response = client.get(
        f"{_versions_url(tenant['product'].id)}?page=1&page_size=2",
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pagination"]["total"] == 3
    assert data["pagination"]["total_pages"] == 2
    assert data["pagination"]["has_next"] is True
    assert len(data["items"]) == 2


def test_versions_default_sort_version_number_desc(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-versions-sort")
    for index in range(3):
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=_snapshot(title=f"Sort Title {index}"),
            idempotency_key=str(uuid.uuid4()),
            marketplace="Amazon",
        )

    response = client.get(
        _versions_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    numbers = [item["version_number"] for item in response.json()["data"]["items"]]
    assert numbers == sorted(numbers, reverse=True)


def test_versions_pagination_is_stable(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-versions-stable")
    for index in range(4):
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=_snapshot(title=f"Stable Title {index}"),
            idempotency_key=str(uuid.uuid4()),
            marketplace="Amazon",
        )

    first = client.get(
        f"{_versions_url(tenant['product'].id)}?page=1&page_size=2",
        headers=auth_header(tenant["user"]),
    ).json()["data"]["items"]
    second = client.get(
        f"{_versions_url(tenant['product'].id)}?page=1&page_size=2",
        headers=auth_header(tenant["user"]),
    ).json()["data"]["items"]
    assert [item["id"] for item in first] == [item["id"] for item in second]


def test_versions_beyond_last_page_returns_empty_items(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-versions-beyond")
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    response = client.get(
        f"{_versions_url(tenant['product'].id)}?page=99&page_size=20",
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_versions_page_size_over_limit_returns_422(
    client, tenant_bundle, auth_header
):
    tenant = tenant_bundle("listing-versions-page-size")
    response = client.get(
        f"{_versions_url(tenant['product'].id)}?page_size=101",
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 422


def test_versions_only_one_is_current(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-versions-current-flag")
    for index in range(3):
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=_snapshot(title=f"Current Flag {index}"),
            idempotency_key=str(uuid.uuid4()),
            marketplace="Amazon",
        )

    response = client.get(
        _versions_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    flags = [item["is_current"] for item in response.json()["data"]["items"]]
    assert flags.count(True) == 1


def test_versions_cross_tenant_returns_404(client, tenant_bundle, auth_header):
    owner = tenant_bundle("listing-versions-owner")
    intruder = tenant_bundle("listing-versions-intruder")
    response = client.get(
        _versions_url(owner["product"].id),
        headers=auth_header(intruder["user"]),
    )
    assert response.status_code == 404


def test_versions_do_not_leak_other_products(
    client, tenant_bundle, auth_header, idempotency_header, db_session, user_factory
):
    tenant = tenant_bundle("listing-versions-scope")
    user = tenant["user"]
    other_product = Product(
        user_id=user.id,
        project_id=tenant["project"].id,
        name="Other product",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    db_session.add(other_product)
    db_session.commit()
    db_session.refresh(other_product)

    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=user.id,
        snapshot=_snapshot(title="Primary Product Version"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    import_listing_version(
        db_session,
        product_id=other_product.id,
        current_user_id=user.id,
        snapshot=_snapshot(title="Other Product Version"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )

    response = client.get(
        _versions_url(tenant["product"].id),
        headers=auth_header(user),
    )
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["product_id"] == str(tenant["product"].id)


def test_versions_response_excludes_internal_fields(
    client, tenant_bundle, auth_header, idempotency_header, db_session
):
    tenant = tenant_bundle("listing-versions-no-internal")
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    response = client.get(
        _versions_url(tenant["product"].id),
        headers=auth_header(tenant["user"]),
    )
    _assert_no_internal_fields(response.json())


def test_list_listing_versions_executes_three_sql_statements(
    engine,
    db_session,
    tenant_bundle,
):
    tenant = tenant_bundle("listing-service-sql-count")
    for index in range(25):
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=_snapshot(title=f"Service SQL {index}"),
            idempotency_key=str(uuid.uuid4()),
            marketplace="Amazon",
        )

    statements = _run_list_listing_versions_with_sql_capture(engine, db_session, tenant)
    _assert_three_list_versions_selects(statements)

    for index in range(25, 50):
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=_snapshot(title=f"Service SQL Extra {index}"),
            idempotency_key=str(uuid.uuid4()),
            marketplace="Amazon",
        )

    statements = _run_list_listing_versions_with_sql_capture(engine, db_session, tenant)
    _assert_three_list_versions_selects(statements)


def test_versions_endpoint_calls_list_service_once(
    client,
    tenant_bundle,
    auth_header,
    idempotency_header,
    db_session,
):
    tenant = tenant_bundle("listing-versions-endpoint")
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )

    with patch(
        "app.api.listing.list_listing_versions",
        wraps=list_listing_versions,
    ) as list_mock:
        response = client.get(
            f"{_versions_url(tenant['product'].id)}?page=1&page_size=20",
            headers=auth_header(tenant["user"]),
        )
        assert response.status_code == 200
        assert list_mock.call_count == 1


def _listing_version_schema_names(openapi_schema: dict) -> set[str]:
    names: set[str] = set()
    components = openapi_schema.get("components", {}).get("schemas", {})
    for name, schema in components.items():
        if name.startswith("ListingVersionResponse"):
            names.add(name)
        props = schema.get("properties", {})
        if "version_number" in props and "backend_keywords" in props and "is_current" in props:
            names.add(name)
    return names


def test_openapi_lists_listing_paths(client):
    schema = client.app.openapi()
    paths = schema["paths"]
    assert "/api/v1/products/{product_id}/listing/import" in paths
    assert "/api/v1/products/{product_id}/listing/current" in paths
    assert "/api/v1/products/{product_id}/listing/versions" in paths


def test_openapi_import_declares_200_and_201_with_typed_schema(client):
    schema = client.app.openapi()
    post = schema["paths"]["/api/v1/products/{product_id}/listing/import"]["post"]
    assert "200" in post["responses"]
    assert "201" in post["responses"]
    for status_code in ("200", "201"):
        content = post["responses"][status_code]["content"]["application/json"]["schema"]
        assert content not in ({}, {"type": "object"})
        assert "$ref" in content or "properties" in content


def test_openapi_success_schemas_are_typed(client):
    schema = client.app.openapi()
    current_get = schema["paths"]["/api/v1/products/{product_id}/listing/current"]["get"]
    versions_get = schema["paths"]["/api/v1/products/{product_id}/listing/versions"]["get"]
    for operation in (current_get, versions_get):
        content = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert content not in ({}, {"type": "object"})
        assert "$ref" in content or "properties" in content


def test_openapi_version_schema_excludes_internal_idempotency_fields(client):
    schema = client.app.openapi()
    version_schema_names = _listing_version_schema_names(schema)
    assert version_schema_names
    components = schema["components"]["schemas"]
    for name in version_schema_names:
        props = components[name].get("properties", {})
        assert "operation_idempotency_key" not in props
        assert "request_hash" not in props
