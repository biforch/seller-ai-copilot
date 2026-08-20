"""HTTP API tests for tenant-scoped Amazon marketplace operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import status

from app.api.amazon_marketplaces_deps import (
    build_amazon_account_runtime_resolver,
    get_amazon_account_runtime_resolver,
    get_amazon_marketplace_refresh_service_factory,
)
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_SYNC_IN_PROGRESS,
    AmazonError,
    amazon_sync_in_progress_error,
)
from app.main import app
from app.models.amazon_account import AmazonAccount
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.services.amazon_account_service import AmazonAccountService
from app.services.amazon_marketplace_refresh_service import MarketplaceRefreshResult
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, OTHER_FAKE_A32_REFRESH_TOKEN

BASE_URL = "/api/v1/amazon/accounts"


def _marketplaces_url(account_id: uuid.UUID) -> str:
    return f"{BASE_URL}/{account_id}/marketplaces"


def _refresh_url(account_id: uuid.UUID) -> str:
    return f"{_marketplaces_url(account_id)}/refresh"


def _create_account(
    db_session,
    user,
    token_encryption_service,
    *,
    token: str,
    region: str = "na",
    endpoint_mode: str = "production",
) -> AmazonAccount:
    service = AmazonAccountService(db_session, token_encryption_service)
    summary = service.create_account(
        user_id=user.id,
        region=region,
        endpoint_mode=endpoint_mode,
        plaintext_refresh_token=token,
    )
    account = db_session.get(AmazonAccount, summary.id)
    assert account is not None
    return account


def _seed_marketplace(
    db_session,
    account: AmazonAccount,
    *,
    marketplace_id: str = "ATVPDKIKX0DER",
    country_code: str = "US",
    participating: bool = True,
    suspended_listings: bool = False,
    is_active: bool = True,
) -> AmazonMarketplaceParticipation:
    row = AmazonMarketplaceParticipation(
        amazon_account_id=account.id,
        marketplace_id=marketplace_id,
        marketplace_name=f"Marketplace {country_code}",
        country_code=country_code,
        default_currency_code="USD",
        default_language_code="en_US",
        domain_name="amazon.test",
        participating=participating,
        suspended_listings=suspended_listings,
        is_active=is_active,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _assert_private_headers(response) -> None:
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_list_marketplaces_empty(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-marketplaces-empty@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    response = client.get(_marketplaces_url(account.id), headers=auth_header(user))
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["data"] == {"items": [], "total": 0}
    _assert_private_headers(response)


def test_list_marketplaces_returns_public_snapshot(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-marketplaces-list@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    row = _seed_marketplace(db_session, account)
    response = client.get(_marketplaces_url(account.id), headers=auth_header(user))
    assert response.status_code == status.HTTP_200_OK
    item = response.json()["data"]["items"][0]
    assert item["marketplace_id"] == row.marketplace_id
    assert item["sync_eligible"] is True
    assert set(item) == {
        "marketplace_id",
        "marketplace_name",
        "country_code",
        "default_currency_code",
        "default_language_code",
        "domain_name",
        "participating",
        "suspended_listings",
        "is_active",
        "sync_eligible",
        "last_seen_at",
        "created_at",
        "updated_at",
    }
    assert "selling_partner_id" not in response.text
    assert "refresh_token" not in response.text
    assert "account_key" not in response.text


@pytest.mark.parametrize(
    ("participating", "suspended", "active"),
    [(False, False, True), (True, True, True), (True, False, False)],
)
def test_list_sync_eligible_requires_all_flags(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    participating: bool,
    suspended: bool,
    active: bool,
):
    user = user_factory(f"amazon-marketplaces-flags-{uuid.uuid4()}@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-{uuid.uuid4()}",
    )
    _seed_marketplace(
        db_session,
        account,
        participating=participating,
        suspended_listings=suspended,
        is_active=active,
    )
    response = client.get(_marketplaces_url(account.id), headers=auth_header(user))
    assert response.json()["data"]["items"][0]["sync_eligible"] is False


def test_list_marketplaces_is_tenant_scoped(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    owner = user_factory("amazon-marketplaces-owner@example.com")
    other = user_factory("amazon-marketplaces-other@example.com")
    account = _create_account(
        db_session,
        owner,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    _seed_marketplace(db_session, account)
    response = client.get(_marketplaces_url(account.id), headers=auth_header(other))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error_code"] == AMAZON_ACCOUNT_NOT_FOUND
    _assert_private_headers(response)


@pytest.mark.parametrize("method", ["get", "post"])
def test_marketplace_endpoints_require_auth(client, method: str):
    url = _marketplaces_url(uuid.uuid4())
    if method == "post":
        url = f"{url}/refresh"
    response = getattr(client, method)(url)
    assert response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}


def test_refresh_passes_tenant_and_account_region_to_service(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-marketplaces-refresh@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
        region="eu",
    )
    user_id = user.id
    account_id = account.id
    calls: list[tuple[object, ...]] = []

    class FakeRefreshService:
        async def refresh_marketplace_participations(self, *, user_id, account_id):
            calls.append(("refresh", user_id, account_id))
            return MarketplaceRefreshResult(
                account_id=account_id,
                sync_log_id=uuid.uuid4(),
                items_seen=2,
                items_written=2,
                items_deactivated=1,
                request_id="request-id-not-exposed",
            )

    def factory(region: str, endpoint_mode: str):
        calls.append(("factory", region, endpoint_mode))
        return FakeRefreshService()

    app.dependency_overrides[get_amazon_marketplace_refresh_service_factory] = lambda: factory
    try:
        response = client.post(_refresh_url(account_id), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_marketplace_refresh_service_factory, None)

    assert response.status_code == status.HTTP_200_OK
    assert calls == [
        ("factory", "eu", "production"),
        ("refresh", user_id, account_id),
    ]
    data = response.json()["data"]
    assert data["account_id"] == str(account_id)
    assert data["items_seen"] == 2
    assert data["items_written"] == 2
    assert data["items_deactivated"] == 1
    assert "request_id" not in data
    _assert_private_headers(response)


def test_refresh_cross_tenant_does_not_build_heavy_service(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    owner = user_factory("amazon-marketplaces-refresh-owner@example.com")
    other = user_factory("amazon-marketplaces-refresh-other@example.com")
    account = _create_account(
        db_session,
        owner,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    factory_calls = 0

    def factory(region: str, endpoint_mode: str):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("cross-tenant request must not build refresh dependencies")

    app.dependency_overrides[get_amazon_marketplace_refresh_service_factory] = lambda: factory
    try:
        response = client.post(_refresh_url(account.id), headers=auth_header(other))
    finally:
        app.dependency_overrides.pop(get_amazon_marketplace_refresh_service_factory, None)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error_code"] == AMAZON_ACCOUNT_NOT_FOUND
    assert factory_calls == 0


def test_account_runtime_resolver_rolls_back_before_external_work():
    expected_user_id = uuid.uuid4()
    expected_account_id = uuid.uuid4()

    class FakeQuery:
        def filter(self, *args):
            return self

        def one_or_none(self):
            return AmazonAccount(
                id=expected_account_id,
                user_id=expected_user_id,
                account_key=str(uuid.uuid4()),
                region="na",
                endpoint_mode="production",
                status="active",
                refresh_token_ciphertext=b"opaque",
                refresh_token_key_version=1,
                refresh_token_fingerprint="f" * 64,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    class FakeSession:
        def __init__(self):
            self.rolled_back = False

        def query(self, model):
            return FakeQuery()

        def rollback(self):
            self.rolled_back = True

    fake_session = FakeSession()
    resolver = build_amazon_account_runtime_resolver(fake_session)  # type: ignore[arg-type]
    summary = resolver(expected_user_id, expected_account_id)
    assert summary.id == expected_account_id
    assert fake_session.rolled_back is True


def test_refresh_amazon_error_is_stable_and_private(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-marketplaces-refresh-error@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=OTHER_FAKE_A32_REFRESH_TOKEN,
    )

    class FailingRefreshService:
        async def refresh_marketplace_participations(self, *, user_id, account_id):
            raise amazon_sync_in_progress_error()

    app.dependency_overrides[get_amazon_marketplace_refresh_service_factory] = (
        lambda: lambda _region, _mode: FailingRefreshService()
    )
    try:
        response = client.post(_refresh_url(account.id), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_marketplace_refresh_service_factory, None)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["error_code"] == AMAZON_SYNC_IN_PROGRESS
    _assert_private_headers(response)


def test_refresh_dynamic_error_message_is_not_exposed(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-marketplaces-refresh-canary@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{OTHER_FAKE_A32_REFRESH_TOKEN}-canary",
    )

    class FailingRefreshService:
        async def refresh_marketplace_participations(self, *, user_id, account_id):
            raise AmazonError(
                "CANARY_DYNAMIC_DETAIL",
                error_code=AMAZON_SYNC_IN_PROGRESS,
                status_code=409,
            )

    app.dependency_overrides[get_amazon_marketplace_refresh_service_factory] = (
        lambda: lambda _region, _mode: FailingRefreshService()
    )
    try:
        response = client.post(_refresh_url(account.id), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_marketplace_refresh_service_factory, None)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "CANARY" not in response.text


def test_marketplace_openapi_contract_is_authenticated_and_public():
    schema = app.openapi()
    list_operation = schema["paths"][
        "/api/v1/amazon/accounts/{account_id}/marketplaces"
    ]["get"]
    refresh_operation = schema["paths"][
        "/api/v1/amazon/accounts/{account_id}/marketplaces/refresh"
    ]["post"]
    assert list_operation["security"] == [{"cookieAuth": []}]
    assert refresh_operation["security"] == [{"cookieAuth": []}]
    serialized = str(schema["components"]["schemas"])
    for sensitive in (
        "selling_partner_id",
        "refresh_token",
        "account_key",
        "sync_lease_id",
    ):
        assert sensitive not in serialized


def test_refresh_result_schema_rejects_negative_counts():
    from app.schemas.amazon_marketplaces import AmazonMarketplaceRefreshResponse

    with pytest.raises(ValueError):
        AmazonMarketplaceRefreshResponse(
            account_id=uuid.uuid4(),
            sync_log_id=uuid.uuid4(),
            items_seen=-1,
            items_written=0,
            items_deactivated=0,
        )


def test_marketplace_read_does_not_change_account_or_participation(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-marketplaces-no-write@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-no-write",
    )
    row = _seed_marketplace(db_session, account)
    account_updated_at = account.updated_at
    row_updated_at = row.updated_at

    response = client.get(_marketplaces_url(account.id), headers=auth_header(user))
    assert response.status_code == status.HTTP_200_OK
    db_session.refresh(account)
    db_session.refresh(row)
    assert account.updated_at == account_updated_at
    assert row.updated_at == row_updated_at


def test_refresh_response_timestamp_is_not_fabricated(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    """The refresh contract exposes executor counts, not a router-generated time."""
    user = user_factory("amazon-marketplaces-no-router-time@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-{datetime.now(UTC).timestamp()}",
    )

    class FakeRefreshService:
        async def refresh_marketplace_participations(self, *, user_id, account_id):
            return MarketplaceRefreshResult(
                account_id=account_id,
                sync_log_id=uuid.uuid4(),
                items_seen=0,
                items_written=0,
                items_deactivated=0,
                request_id=None,
            )

    app.dependency_overrides[get_amazon_marketplace_refresh_service_factory] = (
        lambda: lambda _region, _mode: FakeRefreshService()
    )
    try:
        response = client.post(_refresh_url(account.id), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_marketplace_refresh_service_factory, None)

    assert "finished_at" not in response.json()["data"]


def test_refresh_rate_limit_rejects_before_building_additional_service(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory(f"amazon-marketplaces-rate-{uuid.uuid4()}@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-{uuid.uuid4()}",
    )
    account_summary = AmazonAccountService(
        db_session,
        token_encryption_service,
    ).get_account_for_user(user_id=user.id, account_id=account.id)
    factory_calls = 0

    class FakeRefreshService:
        async def refresh_marketplace_participations(self, *, user_id, account_id):
            return MarketplaceRefreshResult(
                account_id=account_id,
                sync_log_id=uuid.uuid4(),
                items_seen=0,
                items_written=0,
                items_deactivated=0,
                request_id=None,
            )

    def factory(_region: str, _mode: str):
        nonlocal factory_calls
        factory_calls += 1
        return FakeRefreshService()

    app.dependency_overrides[get_amazon_account_runtime_resolver] = (
        lambda: lambda _user_id, _account_id: account_summary
    )
    app.dependency_overrides[get_amazon_marketplace_refresh_service_factory] = lambda: factory
    headers = auth_header(user)
    try:
        responses = [
            client.post(_refresh_url(account.id), headers=headers)
            for _ in range(7)
        ]
    finally:
        app.dependency_overrides.pop(get_amazon_account_runtime_resolver, None)
        app.dependency_overrides.pop(get_amazon_marketplace_refresh_service_factory, None)

    assert [response.status_code for response in responses[:6]] == [200] * 6
    assert responses[6].status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert responses[6].json()["code"] == status.HTTP_429_TOO_MANY_REQUESTS
    assert factory_calls == 6
