from datetime import datetime

import pytest
from sqlalchemy import event

from app.models.generation import Generation
from app.models.product import Product
from app.models.project import Project

FIXED_TIMESTAMP = datetime(2026, 6, 1, 12, 0, 0)


@pytest.fixture
def pagination_seed(db_session, user_factory):
    user = user_factory("pagination@example.com")
    other = user_factory("pagination-other@example.com")

    projects = []
    for index in range(25):
        project = Project(
            user_id=user.id,
            name=f"Project {index:02d}",
            platform="Amazon",
            market="USA",
            status="active" if index % 2 == 0 else "paused",
        )
        db_session.add(project)
        projects.append(project)
    db_session.flush()

    for index, project in enumerate(projects[:15]):
        product = Product(
            user_id=user.id,
            project_id=project.id,
            name=f"Product {index}",
            category="Electronics",
            platform="Amazon",
            market="USA",
        )
        db_session.add(product)
        db_session.flush()
        for gen_index in range(index % 4):
            db_session.add(
                Generation(
                    user_id=user.id,
                    product_id=product.id,
                    project_id=project.id,
                    type="listing" if gen_index % 2 == 0 else "keywords",
                    input={"name": "test"},
                    output={"title": "t"},
                    tokens_used=10,
                )
            )

    foreign_project = Project(
        user_id=other.id,
        name="Foreign",
        platform="Amazon",
        market="USA",
    )
    db_session.add(foreign_project)
    db_session.commit()

    return {"user": user, "other": other, "projects": projects, "foreign_project": foreign_project}


def _items(response):
    return response.json()["data"]["items"]


def _pagination(response):
    return response.json()["data"]["pagination"]


def test_projects_default_pagination(client, pagination_seed, auth_header):
    response = client.get("/api/v1/projects", headers=auth_header(pagination_seed["user"]))
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["items"]) == 20
    pagination = data["pagination"]
    assert pagination["page"] == 1
    assert pagination["page_size"] == 20
    assert pagination["total"] == 25
    assert pagination["total_pages"] == 2
    assert pagination["has_next"] is True
    assert pagination["has_previous"] is False


def test_projects_custom_page_size(client, pagination_seed, auth_header):
    response = client.get(
        "/api/v1/projects?page=2&page_size=10",
        headers=auth_header(pagination_seed["user"]),
    )
    assert response.status_code == 200
    pagination = _pagination(response)
    assert pagination["page"] == 2
    assert pagination["page_size"] == 10
    assert len(_items(response)) == 10
    assert pagination["has_previous"] is True


def test_projects_page_size_over_max_rejected(client, pagination_seed, auth_header):
    response = client.get(
        "/api/v1/projects?page_size=101",
        headers=auth_header(pagination_seed["user"]),
    )
    assert response.status_code == 422


def test_projects_invalid_sort_by_rejected(client, pagination_seed, auth_header):
    response = client.get(
        "/api/v1/projects?sort_by=id;drop table",
        headers=auth_header(pagination_seed["user"]),
    )
    assert response.status_code == 422
    assert response.json()["message"] == "Invalid sort_by: id;drop table"


def test_projects_sort_asc_and_desc(client, pagination_seed, auth_header):
    asc_resp = client.get(
        "/api/v1/projects?sort_by=name&sort_order=asc&page_size=100",
        headers=auth_header(pagination_seed["user"]),
    )
    desc_resp = client.get(
        "/api/v1/projects?sort_by=name&sort_order=desc&page_size=100",
        headers=auth_header(pagination_seed["user"]),
    )
    asc_names = [item["name"] for item in _items(asc_resp)]
    desc_names = [item["name"] for item in _items(desc_resp)]
    assert asc_names == sorted(asc_names)
    assert desc_names == sorted(desc_names, reverse=True)


def test_projects_empty_list(client, auth_header, user_factory):
    user = user_factory("empty-projects@example.com")
    response = client.get("/api/v1/projects", headers=auth_header(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"] == []
    assert data["pagination"]["total"] == 0
    assert data["pagination"]["total_pages"] == 0
    assert data["pagination"]["has_next"] is False


def test_projects_page_beyond_total_returns_empty_items(client, pagination_seed, auth_header):
    response = client.get(
        "/api/v1/projects?page=99&page_size=20",
        headers=auth_header(pagination_seed["user"]),
    )
    assert response.status_code == 200
    assert _items(response) == []
    pagination = _pagination(response)
    assert pagination["page"] == 99
    assert pagination["total"] == 25


def test_exact_project_and_product_counts(client, db_session, user_factory, auth_header):
    owner = user_factory("exact-counts@example.com")
    foreign = user_factory("exact-counts-foreign@example.com")

    project_a = Project(
        user_id=owner.id,
        name="Project A",
        platform="Amazon",
        market="USA",
    )
    project_b = Project(
        user_id=owner.id,
        name="Project B",
        platform="Amazon",
        market="USA",
    )
    foreign_project = Project(
        user_id=foreign.id,
        name="Foreign Project",
        platform="Amazon",
        market="USA",
    )
    db_session.add_all([project_a, project_b, foreign_project])
    db_session.flush()

    product_a1 = Product(
        user_id=owner.id,
        project_id=project_a.id,
        name="Product 1",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    product_a2 = Product(
        user_id=owner.id,
        project_id=project_a.id,
        name="Product 2",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    product_b1 = Product(
        user_id=owner.id,
        project_id=project_b.id,
        name="Product 3",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    foreign_product = Product(
        user_id=foreign.id,
        project_id=foreign_project.id,
        name="Foreign Product",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    db_session.add_all([product_a1, product_a2, product_b1, foreign_product])
    db_session.flush()

    for _ in range(2):
        db_session.add(
            Generation(
                user_id=owner.id,
                product_id=product_a1.id,
                project_id=project_a.id,
                type="listing",
                input={"name": "a1"},
                output={"title": "t"},
                tokens_used=10,
            )
        )
    db_session.add(
        Generation(
            user_id=owner.id,
            product_id=product_a2.id,
            project_id=project_a.id,
            type="keywords",
            input={"name": "a2"},
            output={"keywords": ["k"]},
            tokens_used=5,
        )
    )
    db_session.add(
        Generation(
            user_id=foreign.id,
            product_id=foreign_product.id,
            project_id=foreign_project.id,
            type="listing",
            input={"name": "foreign"},
            output={"title": "x"},
            tokens_used=7,
        )
    )
    db_session.commit()

    project_response = client.get(
        "/api/v1/projects?page_size=100&sort_by=name&sort_order=asc",
        headers=auth_header(owner),
    )
    assert project_response.status_code == 200
    projects_by_name = {item["name"]: item for item in _items(project_response)}
    assert set(projects_by_name) == {"Project A", "Project B"}
    assert projects_by_name["Project A"]["product_count"] == 2
    assert projects_by_name["Project A"]["generation_count"] == 3
    assert projects_by_name["Project B"]["product_count"] == 1
    assert projects_by_name["Project B"]["generation_count"] == 0

    product_response = client.get(
        "/api/v1/products?page_size=100&sort_by=name&sort_order=asc",
        headers=auth_header(owner),
    )
    assert product_response.status_code == 200
    products_by_name = {item["name"]: item for item in _items(product_response)}
    assert set(products_by_name) == {"Product 1", "Product 2", "Product 3"}
    assert products_by_name["Product 1"]["generations_count"] == 2
    assert products_by_name["Product 2"]["generations_count"] == 1
    assert products_by_name["Product 3"]["generations_count"] == 0

    foreign_listing = client.get("/api/v1/projects", headers=auth_header(foreign))
    foreign_names = {item["name"] for item in _items(foreign_listing)}
    assert foreign_names == {"Foreign Project"}
    assert foreign_listing.json()["data"]["pagination"]["total"] == 1


def test_project_stable_pagination_with_equal_timestamps(client, db_session, user_factory, auth_header):
    user = user_factory("stable-projects@example.com")
    project_ids: list[str] = []
    for index in range(5):
        project = Project(
            user_id=user.id,
            name=f"Stable Project {index}",
            platform="Amazon",
            market="USA",
            created_at=FIXED_TIMESTAMP,
            updated_at=FIXED_TIMESTAMP,
        )
        db_session.add(project)
        db_session.flush()
        project_ids.append(str(project.id))
    db_session.commit()

    headers = auth_header(user)
    page1 = client.get(
        "/api/v1/projects?page=1&page_size=2&sort_by=updated_at&sort_order=desc",
        headers=headers,
    )
    page2 = client.get(
        "/api/v1/projects?page=2&page_size=2&sort_by=updated_at&sort_order=desc",
        headers=headers,
    )
    assert page1.status_code == 200
    assert page2.status_code == 200

    ids_page1 = [item["id"] for item in _items(page1)]
    ids_page2 = [item["id"] for item in _items(page2)]
    assert len(ids_page1) == 2
    assert len(ids_page2) == 2
    assert set(ids_page1).isdisjoint(ids_page2)

    expected_order = sorted(project_ids, reverse=True)
    assert ids_page1 + ids_page2 == expected_order[:4]
    assert _pagination(page1)["total"] == 5


def test_product_stable_pagination_with_equal_timestamps(client, db_session, user_factory, auth_header):
    user = user_factory("stable-products@example.com")
    project = Project(user_id=user.id, name="Stable", platform="Amazon", market="USA")
    db_session.add(project)
    db_session.flush()

    product_ids: list[str] = []
    for index in range(5):
        product = Product(
            user_id=user.id,
            project_id=project.id,
            name=f"Stable Product {index}",
            category="Electronics",
            platform="Amazon",
            market="USA",
            created_at=FIXED_TIMESTAMP,
        )
        db_session.add(product)
        db_session.flush()
        product_ids.append(str(product.id))
    db_session.commit()

    headers = auth_header(user)
    page1 = client.get(
        "/api/v1/products?page=1&page_size=2&sort_by=created_at&sort_order=desc",
        headers=headers,
    )
    page2 = client.get(
        "/api/v1/products?page=2&page_size=2&sort_by=created_at&sort_order=desc",
        headers=headers,
    )
    assert page1.status_code == 200
    assert page2.status_code == 200

    ids_page1 = [item["id"] for item in _items(page1)]
    ids_page2 = [item["id"] for item in _items(page2)]
    assert len(ids_page1) == 2
    assert len(ids_page2) == 2
    assert set(ids_page1).isdisjoint(ids_page2)

    expected_order = sorted(product_ids, reverse=True)
    assert ids_page1 + ids_page2 == expected_order[:4]
    assert _pagination(page1)["total"] == 5


def test_projects_tenant_isolation(client, pagination_seed, auth_header):
    response = client.get("/api/v1/projects", headers=auth_header(pagination_seed["user"]))
    ids = {item["id"] for item in _items(response)}
    assert str(pagination_seed["foreign_project"].id) not in ids


def test_products_default_pagination(client, pagination_seed, auth_header):
    response = client.get("/api/v1/products", headers=auth_header(pagination_seed["user"]))
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["items"]) == 15
    assert data["pagination"]["total"] == 15


def test_products_invalid_sort_by_rejected(client, pagination_seed, auth_header):
    response = client.get(
        "/api/v1/products?sort_by=updated_at",
        headers=auth_header(pagination_seed["user"]),
    )
    assert response.status_code == 422


def test_project_detail_products_paginated(client, pagination_seed, auth_header, db_session):
    project_with_many = pagination_seed["projects"][1]
    for index in range(12):
        db_session.add(
            Product(
                user_id=pagination_seed["user"].id,
                project_id=project_with_many.id,
                name=f"Bulk Product {index}",
                category="Home",
                platform="Amazon",
                market="USA",
            )
        )
    db_session.commit()

    response = client.get(
        f"/api/v1/projects/{project_with_many.id}?page=1&page_size=5",
        headers=auth_header(pagination_seed["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["product_count"] >= 13
    assert len(data["products"]["items"]) == 5
    assert data["products"]["pagination"]["total"] >= 13


def test_project_detail_regression(client, tenant_bundle, auth_header):
    bundle = tenant_bundle("detail-regression")
    response = client.get(
        f"/api/v1/projects/{bundle['project'].id}",
        headers=auth_header(bundle["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(bundle["project"].id)
    assert isinstance(data["products"]["items"], list)


def test_product_detail_regression(client, tenant_bundle, auth_header):
    bundle = tenant_bundle("product-detail-regression")
    response = client.get(
        f"/api/v1/products/{bundle['product'].id}",
        headers=auth_header(bundle["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stats"]["total_generations"] == 0
    assert "generations" in data


@pytest.fixture
def query_counter(engine):
    counter = {"count": 0}

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    yield counter
    event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def test_project_list_query_count_is_constant(
    client,
    db_session,
    user_factory,
    auth_header,
    query_counter,
):
    user = user_factory("query-count-projects@example.com")
    for index in range(30):
        project = Project(
            user_id=user.id,
            name=f"QC Project {index}",
            platform="Amazon",
            market="USA",
        )
        db_session.add(project)
    db_session.commit()

    query_counter["count"] = 0
    response = client.get(
        "/api/v1/projects?page=1&page_size=20",
        headers=auth_header(user),
    )
    assert response.status_code == 200
    baseline = query_counter["count"]
    assert baseline > 0

    for _ in range(5):
        project = Project(
            user_id=user.id,
            name="Extra project",
            platform="Amazon",
            market="USA",
        )
        db_session.add(project)
    db_session.commit()

    query_counter["count"] = 0
    response = client.get(
        "/api/v1/projects?page=1&page_size=20",
        headers=auth_header(user),
    )
    assert response.status_code == 200
    assert query_counter["count"] == baseline


def test_product_list_query_count_is_constant(
    client,
    db_session,
    user_factory,
    auth_header,
    query_counter,
):
    user = user_factory("query-count-products@example.com")
    project = Project(user_id=user.id, name="QC", platform="Amazon", market="USA")
    db_session.add(project)
    db_session.flush()

    def seed_products(count: int) -> None:
        for index in range(count):
            db_session.add(
                Product(
                    user_id=user.id,
                    project_id=project.id,
                    name=f"QC Product {index}",
                    category="Electronics",
                    platform="Amazon",
                    market="USA",
                )
            )
        db_session.commit()

    seed_products(25)
    query_counter["count"] = 0
    response = client.get(
        "/api/v1/products?page=1&page_size=20",
        headers=auth_header(user),
    )
    assert response.status_code == 200
    baseline = query_counter["count"]

    seed_products(10)
    query_counter["count"] = 0
    response = client.get(
        "/api/v1/products?page=1&page_size=20",
        headers=auth_header(user),
    )
    assert response.status_code == 200
    assert query_counter["count"] == baseline


def test_cross_tenant_counts_excluded(client, db_session, user_factory, auth_header):
    owner = user_factory("stats-owner@example.com")
    intruder = user_factory("stats-intruder@example.com")

    owner_project = Project(user_id=owner.id, name="Owner", platform="Amazon", market="USA")
    foreign_project = Project(user_id=intruder.id, name="Foreign", platform="Amazon", market="USA")
    db_session.add_all([owner_project, foreign_project])
    db_session.flush()

    owner_product = Product(
        user_id=owner.id,
        project_id=owner_project.id,
        name="Owner Product",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    foreign_product = Product(
        user_id=intruder.id,
        project_id=foreign_project.id,
        name="Foreign Product",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    db_session.add_all([owner_product, foreign_product])
    db_session.flush()
    db_session.add(
        Generation(
            user_id=intruder.id,
            product_id=foreign_product.id,
            project_id=foreign_project.id,
            type="listing",
            input={"name": "x"},
            output={"title": "y"},
            tokens_used=5,
        )
    )
    db_session.commit()

    response = client.get("/api/v1/projects", headers=auth_header(owner))
    items = _items(response)
    assert len(items) == 1
    assert items[0]["product_count"] == 1
    assert items[0]["generation_count"] == 0
    assert str(foreign_project.id) not in {item["id"] for item in items}

    product_response = client.get("/api/v1/products", headers=auth_header(owner))
    product_items = _items(product_response)
    assert len(product_items) == 1
    assert product_items[0]["generations_count"] == 0
    assert str(foreign_product.id) not in {item["id"] for item in product_items}


def test_sync_def_routes_still_work(client, user_factory, auth_header):
    user = user_factory("sync-route@example.com")
    headers = auth_header(user)
    assert client.get("/api/v1/projects", headers=headers).status_code == 200
    assert client.get("/api/v1/products", headers=headers).status_code == 200
    assert client.get("/api/v1/user/usage", headers=headers).status_code == 200
