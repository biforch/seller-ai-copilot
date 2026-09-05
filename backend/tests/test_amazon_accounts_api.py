"""HTTP API tests for tenant-scoped Amazon account read endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import status

from app.api.amazon_accounts_deps import get_amazon_account_read_service
from app.core.exceptions import AMAZON_ACCOUNT_PUBLIC_MESSAGE, public_message_for_amazon_error_code
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AmazonError,
    amazon_account_not_found_error,
)
from app.integrations.amazon.lwa import LwaTokenClient
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.integrations.amazon.transport import HttpxTransport
from app.main import app
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.services.amazon_account_read_service import AmazonAccountReadService
from app.services.amazon_account_service import AmazonAccountService
from tests.fixtures.amazon_a32 import (
    FAKE_A32_REFRESH_TOKEN,
    OTHER_FAKE_A32_REFRESH_TOKEN,
    create_account_via_service,
)

LIST_URL = "/api/v1/amazon/accounts"
CANARY_USER_ID = "00000000-0000-4000-8000-000000000099"
CANARY_ACCOUNT_KEY = "00000000-0000-4000-8000-000000000088"
CANARY_SELLER_ID = "CanarySellerIdForApiTests1"
CANARY_CIPHERTEXT = b"CANARY_CIPHERTEXT_SHOULD_NOT_LEAK"
CANARY_FINGERPRINT = "c" * 64
CANARY_LEASE_ID = "00000000-0000-4000-8000-000000000077"
SENSITIVE_RESPONSE_KEYS = {
    "user_id",
    "account_key",
    "selling_partner_id",
    "refresh_token_ciphertext",
    "refresh_token_fingerprint",
    "refresh_token_key_version",
    "sync_lease_id",
    "sync_lease_expires_at",
}


def _detail_url(account_id: uuid.UUID | str) -> str:
    return f"{LIST_URL}/{account_id}"


def _create_account(
    db_session,
    user,
    token_encryption_service,
    *,
    token: str = FAKE_A32_REFRESH_TOKEN,
    region: str = "na",
    endpoint_mode: str = "sandbox",
    status_value: str = AmazonAccountStatus.ACTIVE,
    seller_id: str | None = None,
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
    if seller_id is not None:
        account.selling_partner_id = seller_id
    if status_value != AmazonAccountStatus.ACTIVE:
        account.status = status_value
    account.sync_lease_id = uuid.uuid4()
    account.sync_lease_expires_at = datetime(2099, 1, 1, tzinfo=UTC)
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def _assert_private_cache_headers(response) -> None:
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Pragma") == "no-cache"


def _assert_public_account_shape(payload: dict) -> None:
    assert set(payload) == {
        "id",
        "region",
        "endpoint_mode",
        "status",
        "last_verified_at",
        "created_at",
        "updated_at",
    }


def _assert_response_excludes_sensitive_values(response_text: str) -> None:
    assert CANARY_USER_ID not in response_text
    assert CANARY_ACCOUNT_KEY not in response_text
    assert CANARY_SELLER_ID not in response_text
    assert "c" * 64 not in response_text
    assert CANARY_LEASE_ID not in response_text
    assert "CANARY_CIPHERTEXT" not in response_text


def test_encryption_constructor_not_called_for_read_api(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    monkeypatch: pytest.MonkeyPatch,
):
    user = user_factory("amazon-accounts-no-encryption-init@example.com")
    account = _create_account(db_session, user, token_encryption_service)

    def _fail_encryption_init(self, *args, **kwargs):
        raise AssertionError("TokenEncryptionService must not be constructed by read API")

    def _fail_build_encryption(*args, **kwargs):
        raise AssertionError("build_token_encryption_service must not be called by read API")

    monkeypatch.setattr(TokenEncryptionService, "__init__", _fail_encryption_init)
    monkeypatch.setattr(
        "app.integrations.amazon.token_encryption_loader.build_token_encryption_service",
        _fail_build_encryption,
    )

    list_response = client.get(LIST_URL, headers=auth_header(user))
    detail_response = client.get(_detail_url(account.id), headers=auth_header(user))
    assert list_response.status_code == status.HTTP_200_OK
    assert detail_response.status_code == status.HTTP_200_OK


def test_read_api_works_when_encryption_settings_unavailable(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    monkeypatch: pytest.MonkeyPatch,
):
    user = user_factory("amazon-accounts-no-encryption-settings@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-no-settings",
    )

    def _fail_build_encryption(*args, **kwargs):
        raise AssertionError("encryption settings must not be required for read API")

    monkeypatch.setattr(
        "app.integrations.amazon.token_encryption_loader.build_token_encryption_service",
        _fail_build_encryption,
    )

    list_response = client.get(LIST_URL, headers=auth_header(user))
    detail_response = client.get(_detail_url(account.id), headers=auth_header(user))
    assert list_response.status_code == status.HTTP_200_OK
    assert detail_response.status_code == status.HTTP_200_OK
    assert list_response.json()["data"]["total"] == 1


def test_read_dependency_only_constructs_read_service_with_db_session(db_session):
    service = get_amazon_account_read_service(db=db_session)
    assert isinstance(service, AmazonAccountReadService)
    assert service._db is db_session


def test_write_service_still_requires_token_encryption_service(db_session, token_encryption_service, user_factory):
    user = user_factory("amazon-accounts-write-encryption@example.com")
    with pytest.raises(TypeError):
        AmazonAccountService(db_session)  # type: ignore[call-arg]

    write_service = AmazonAccountService(db_session, token_encryption_service)
    summary = write_service.create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=f"{OTHER_FAKE_A32_REFRESH_TOKEN}-write-required",
    )
    assert summary.region == "na"


def test_list_empty_accounts(client, user_factory, auth_header):
    user = user_factory("amazon-accounts-empty@example.com")
    response = client.get(LIST_URL, headers=auth_header(user))
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["code"] == 200
    assert body["data"] == {"items": [], "total": 0}
    _assert_private_cache_headers(response)


def test_list_single_account(client, user_factory, auth_header, db_session, token_encryption_service):
    user = user_factory("amazon-accounts-single@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        seller_id=CANARY_SELLER_ID,
    )
    response = client.get(LIST_URL, headers=auth_header(user))
    body = response.json()
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1
    item = body["data"]["items"][0]
    _assert_public_account_shape(item)
    assert item["id"] == str(account.id)
    assert item["region"] == "na"
    _assert_response_excludes_sensitive_values(response.text)


def test_list_multiple_accounts_sorted(client, user_factory, auth_header, db_session, token_encryption_service):
    user = user_factory("amazon-accounts-sort@example.com")
    first = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-sort-1",
        region="na",
    )
    second = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{OTHER_FAKE_A32_REFRESH_TOKEN}-sort-2",
        region="eu",
    )
    third = _create_account(
        db_session,
        user,
        token_encryption_service,
        token=f"{OTHER_FAKE_A32_REFRESH_TOKEN}-sort-3",
        region="fe",
    )
    first.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    second.updated_at = datetime(2026, 1, 3, tzinfo=UTC)
    third.updated_at = datetime(2026, 1, 2, tzinfo=UTC)
    db_session.add_all([first, second, third])
    db_session.commit()

    response = client.get(LIST_URL, headers=auth_header(user))
    ids = [item["id"] for item in response.json()["data"]["items"]]
    assert ids == [str(second.id), str(third.id), str(first.id)]


def test_list_only_current_user_accounts(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    owner = user_factory("amazon-accounts-owner@example.com")
    other = user_factory("amazon-accounts-other@example.com")
    owned = _create_account(db_session, owner, token_encryption_service, token=f"{FAKE_A32_REFRESH_TOKEN}-owner")
    _create_account(db_session, other, token_encryption_service, token=f"{OTHER_FAKE_A32_REFRESH_TOKEN}-other")

    response = client.get(LIST_URL, headers=auth_header(owner))
    body = response.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(owned.id)


def test_detail_success(client, user_factory, auth_header, db_session, token_encryption_service):
    user = user_factory("amazon-accounts-detail@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        seller_id=CANARY_SELLER_ID,
        endpoint_mode="production",
    )
    response = client.get(_detail_url(account.id), headers=auth_header(user))
    assert response.status_code == status.HTTP_200_OK
    payload = response.json()["data"]
    _assert_public_account_shape(payload)
    assert payload["id"] == str(account.id)
    assert payload["endpoint_mode"] == "production"
    _assert_private_cache_headers(response)
    _assert_response_excludes_sensitive_values(response.text)


def test_detail_not_found(client, user_factory, auth_header):
    user = user_factory("amazon-accounts-missing@example.com")
    missing_id = uuid.uuid4()
    response = client.get(_detail_url(missing_id), headers=auth_header(user))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    body = response.json()
    assert body["error_code"] == AMAZON_ACCOUNT_NOT_FOUND
    assert body["message"] == public_message_for_amazon_error_code(AMAZON_ACCOUNT_NOT_FOUND)
    _assert_private_cache_headers(response)


def test_detail_cross_tenant(client, user_factory, auth_header, db_session, token_encryption_service):
    owner = user_factory("amazon-accounts-detail-owner@example.com")
    other = user_factory("amazon-accounts-detail-other@example.com")
    account = _create_account(db_session, owner, token_encryption_service, token=f"{FAKE_A32_REFRESH_TOKEN}-detail-owner")
    response = client.get(_detail_url(account.id), headers=auth_header(other))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error_code"] == AMAZON_ACCOUNT_NOT_FOUND


def test_detail_not_found_and_cross_tenant_responses_match(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    owner = user_factory("amazon-accounts-match-owner@example.com")
    other = user_factory("amazon-accounts-match-other@example.com")
    account = _create_account(db_session, owner, token_encryption_service, token=f"{FAKE_A32_REFRESH_TOKEN}-match-owner")
    missing = client.get(_detail_url(uuid.uuid4()), headers=auth_header(other))
    cross = client.get(_detail_url(account.id), headers=auth_header(other))
    assert missing.status_code == cross.status_code == status.HTTP_404_NOT_FOUND
    assert missing.json() == cross.json()


@pytest.mark.parametrize("url", [LIST_URL, _detail_url(uuid.uuid4())])
def test_unauthenticated_requests_rejected(client, url: str):
    response = client.get(url)
    assert response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}


def test_invalid_token_rejected(client):
    response = client.get(
        LIST_URL,
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["error_code"] == "AUTH_SESSION_INVALID"
    assert "WWW-Authenticate" not in response.headers


def test_detail_invalid_uuid_path(client, user_factory, auth_header):
    user = user_factory("amazon-accounts-invalid-uuid@example.com")
    response = client.get(f"{LIST_URL}/not-a-uuid", headers=auth_header(user))
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_list_response_excludes_sensitive_fields(client, user_factory, auth_header, db_session, token_encryption_service):
    user = user_factory("amazon-accounts-sensitive-list@example.com")
    _create_account(db_session, user, token_encryption_service, seller_id=CANARY_SELLER_ID)
    response = client.get(LIST_URL, headers=auth_header(user))
    serialized = response.text
    for key in SENSITIVE_RESPONSE_KEYS:
        assert key not in serialized
    _assert_response_excludes_sensitive_values(serialized)


def test_detail_response_excludes_sensitive_fields(client, user_factory, auth_header, db_session, token_encryption_service):
    user = user_factory("amazon-accounts-sensitive-detail@example.com")
    account = _create_account(db_session, user, token_encryption_service, seller_id=CANARY_SELLER_ID)
    response = client.get(_detail_url(account.id), headers=auth_header(user))
    serialized = response.text
    for key in SENSITIVE_RESPONSE_KEYS:
        assert key not in serialized
    _assert_response_excludes_sensitive_values(serialized)


def test_openapi_excludes_sensitive_account_fields():
    schema = app.openapi()
    paths = schema["paths"]
    list_schema = paths["/api/v1/amazon/accounts"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    detail_schema = paths["/api/v1/amazon/accounts/{account_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert list_schema["$ref"].endswith("/ApiResponse_AmazonAccountListResponse_")
    assert detail_schema["$ref"].endswith("/ApiResponse_AmazonAccountPublic_")
    public_schema = schema["components"]["schemas"]["AmazonAccountPublic"]
    assert set(public_schema["properties"]) == {
        "id",
        "region",
        "endpoint_mode",
        "status",
        "last_verified_at",
        "created_at",
        "updated_at",
    }
    serialized = str(schema["components"]["schemas"]).lower()
    for key in SENSITIVE_RESPONSE_KEYS:
        assert key not in serialized
    list_security = paths["/api/v1/amazon/accounts"]["get"].get("security")
    detail_security = paths["/api/v1/amazon/accounts/{account_id}"]["get"].get("security")
    assert list_security == [{"cookieAuth": []}]
    assert detail_security == [{"cookieAuth": []}]


def test_read_endpoints_do_not_decrypt_tokens(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    monkeypatch: pytest.MonkeyPatch,
):
    user = user_factory("amazon-accounts-no-decrypt@example.com")
    account = _create_account(db_session, user, token_encryption_service)

    def _fail_decrypt(*args, **kwargs):
        raise AssertionError("decrypt_refresh_token must not be called by read API")

    monkeypatch.setattr(
        token_encryption_service.__class__,
        "decrypt_refresh_token",
        _fail_decrypt,
    )
    list_response = client.get(LIST_URL, headers=auth_header(user))
    detail_response = client.get(_detail_url(account.id), headers=auth_header(user))
    assert list_response.status_code == status.HTTP_200_OK
    assert detail_response.status_code == status.HTTP_200_OK


def test_read_endpoints_do_not_create_lwa_or_transport(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    monkeypatch: pytest.MonkeyPatch,
):
    user = user_factory("amazon-accounts-no-lwa@example.com")
    account = _create_account(db_session, user, token_encryption_service)

    def _fail_transport_init(self, *args, **kwargs):
        raise AssertionError("HttpxTransport must not be created by read API")

    def _fail_lwa_init(self, *args, **kwargs):
        raise AssertionError("LwaTokenClient must not be created by read API")

    monkeypatch.setattr(HttpxTransport, "__init__", _fail_transport_init)
    monkeypatch.setattr(LwaTokenClient, "__init__", _fail_lwa_init)

    assert client.get(LIST_URL, headers=auth_header(user)).status_code == status.HTTP_200_OK
    assert client.get(_detail_url(account.id), headers=auth_header(user)).status_code == status.HTTP_200_OK


def test_read_endpoints_do_not_send_network_requests(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    monkeypatch: pytest.MonkeyPatch,
):
    user = user_factory("amazon-accounts-no-network@example.com")
    account = _create_account(db_session, user, token_encryption_service)

    async def _fail_transport_request(self, *args, **kwargs):
        raise AssertionError("Amazon transport request must not be sent by read API")

    monkeypatch.setattr(HttpxTransport, "request", _fail_transport_request)

    assert client.get(LIST_URL, headers=auth_header(user)).status_code == status.HTTP_200_OK
    assert client.get(_detail_url(account.id), headers=auth_header(user)).status_code == status.HTTP_200_OK


def test_amazon_error_uses_public_handler_contract(client, user_factory, auth_header):
    user = user_factory("amazon-accounts-public-handler@example.com")

    class FailingAccountService:
        def list_accounts_for_user(self, *, user_id: uuid.UUID):
            raise AmazonError(
                "CANARY_DYNAMIC_MESSAGE_SHOULD_NOT_LEAK",
                error_code=AMAZON_ACCOUNT_NOT_FOUND,
                status_code=404,
            )

        def get_account_for_user(self, *, user_id: uuid.UUID, account_id: uuid.UUID):
            raise amazon_account_not_found_error()

    app.dependency_overrides[get_amazon_account_read_service] = lambda: FailingAccountService()
    try:
        list_response = client.get(LIST_URL, headers=auth_header(user))
        detail_response = client.get(_detail_url(uuid.uuid4()), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_account_read_service, None)

    for response in (list_response, detail_response):
        body = response.json()
        assert body["error_code"] == AMAZON_ACCOUNT_NOT_FOUND
        assert body["message"] == AMAZON_ACCOUNT_PUBLIC_MESSAGE
        assert "CANARY" not in response.text


def test_list_total_matches_items_length(client, user_factory, auth_header, db_session, token_encryption_service):
    user = user_factory("amazon-accounts-total@example.com")
    _create_account(db_session, user, token_encryption_service, token=f"{FAKE_A32_REFRESH_TOKEN}-total-1")
    _create_account(db_session, user, token_encryption_service, token=f"{OTHER_FAKE_A32_REFRESH_TOKEN}-total-2")
    body = client.get(LIST_URL, headers=auth_header(user)).json()["data"]
    assert body["total"] == len(body["items"]) == 2


@pytest.mark.parametrize(
    "status_value",
    [
        AmazonAccountStatus.DISABLED,
        AmazonAccountStatus.REAUTHORIZATION_REQUIRED,
        AmazonAccountStatus.ERROR,
    ],
)
def test_detail_reads_non_active_status_safely(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
    status_value: str,
):
    user = user_factory(f"amazon-accounts-status-{status_value}@example.com")
    account = _create_account(
        db_session,
        user,
        token_encryption_service,
        status_value=status_value,
        token=f"{FAKE_A32_REFRESH_TOKEN}-{status_value}",
    )
    payload = client.get(_detail_url(account.id), headers=auth_header(user)).json()["data"]
    assert payload["status"] == status_value


def test_read_endpoints_do_not_mutate_account(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-accounts-no-mutation@example.com")
    account = _create_account(db_session, user, token_encryption_service)
    before_updated_at = account.updated_at
    before_status = account.status
    before_ciphertext = bytes(account.refresh_token_ciphertext)

    client.get(LIST_URL, headers=auth_header(user))
    client.get(_detail_url(account.id), headers=auth_header(user))

    db_session.refresh(account)
    assert account.updated_at == before_updated_at
    assert account.status == before_status
    assert account.refresh_token_ciphertext == before_ciphertext


def test_dependency_override_cleaned_up(client, user_factory, auth_header):
    user = user_factory("amazon-accounts-override-cleanup@example.com")

    class EmptyAccountService:
        def list_accounts_for_user(self, *, user_id: uuid.UUID):
            return []

    app.dependency_overrides[get_amazon_account_read_service] = lambda: EmptyAccountService()
    response = client.get(LIST_URL, headers=auth_header(user))
    app.dependency_overrides.pop(get_amazon_account_read_service, None)
    assert response.json()["data"] == {"items": [], "total": 0}
    assert get_amazon_account_read_service not in app.dependency_overrides


def test_create_account_via_service_still_works_for_fixture(db_session, user_factory, token_encryption_service):
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-fixture-smoke",
    )
    assert summary.user_id == user.id


def test_disconnect_account_api_removes_account(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    user = user_factory("amazon-disconnect-api@example.com")
    account = _create_account(db_session, user, token_encryption_service)
    response = client.delete(_detail_url(account.id), headers=auth_header(user))
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["account_id"] == str(account.id)
    assert body["already_disconnected"] is False
    assert body["disconnected_at"] is not None
    assert db_session.get(AmazonAccount, account.id) is None


def test_disconnect_account_api_is_idempotent(
    client,
    user_factory,
    auth_header,
):
    user = user_factory("amazon-disconnect-api-idempotent@example.com")
    missing_id = uuid.uuid4()
    first = client.delete(_detail_url(missing_id), headers=auth_header(user))
    second = client.delete(_detail_url(missing_id), headers=auth_header(user))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["already_disconnected"] is True
    assert second.json()["data"]["already_disconnected"] is True


def test_disconnect_account_api_rejects_cross_tenant(
    client,
    user_factory,
    auth_header,
    db_session,
    token_encryption_service,
):
    owner = user_factory("amazon-disconnect-owner@example.com")
    other = user_factory("amazon-disconnect-intruder@example.com")
    account = _create_account(db_session, owner, token_encryption_service)
    response = client.delete(_detail_url(account.id), headers=auth_header(other))
    assert response.status_code == 200
    assert response.json()["data"]["already_disconnected"] is True
    assert db_session.get(AmazonAccount, account.id) is not None


def test_capabilities_endpoint_reports_feature_flags(
    client,
    user_factory,
    auth_header,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core.config import settings

    user = user_factory("amazon-capabilities@example.com")
    monkeypatch.setattr(settings, "AMAZON_OAUTH_ENABLED", False)
    monkeypatch.setattr(settings, "AMAZON_SP_API_ENABLED", False)
    response = client.get(f"{LIST_URL.rsplit('/', 1)[0]}/capabilities", headers=auth_header(user))
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload == {"oauth_enabled": False, "sp_api_enabled": False}
