"""Amazon OAuth orchestration service tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import get_password_hash
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CONFIG_INVALID,
    AMAZON_LWA_RATE_LIMITED,
    AMAZON_LWA_UNAVAILABLE,
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
    AMAZON_OAUTH_DISABLED,
    AMAZON_OAUTH_INTENT_INVALID,
    AMAZON_OAUTH_MARKETPLACE_INVALID,
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AMAZON_OAUTH_SELLER_INVALID,
    AMAZON_OAUTH_SELLER_MISMATCH,
    AMAZON_OAUTH_STATE_EXPIRED,
    AMAZON_OAUTH_STATE_INVALID,
    AMAZON_OAUTH_STATE_REPLAY,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
    AMAZON_OAUTH_USER_NOT_FOUND,
    AmazonError,
    amazon_config_invalid_error,
    amazon_oauth_account_persist_failed_error,
    amazon_oauth_disabled_error,
    amazon_oauth_token_exchange_failed_error,
)
from app.integrations.amazon.lwa import (
    LwaAuthorizationCodeResponse,
    LwaTokenClient,
)
from app.integrations.amazon.oauth_urls import AUTHORIZE_CONSENT_PATH
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.integrations.amazon.transport import TransportError, TransportFailureKind
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_oauth_state import AmazonOAuthState, OAuthStateIntent, OAuthStateStatus
from app.models.user import User
from app.services.amazon_account_service import OAUTH_ACCOUNT_ENDPOINT_MODE, AmazonAccountService
from app.services.amazon_oauth_service import AmazonOAuthService, AmazonOAuthStartResult
from app.services.amazon_oauth_state_store import hash_oauth_state_token
from tests.integrations.amazon.conftest import TEST_CLIENT_ID, TEST_CLIENT_SECRET, make_transport

CANARY_STATE = "C" * 43
CANARY_CODE = "CANARY_OAUTH_CODE_SECRET_MARKER"
CANARY_SELLER = "CANARYSELLER123456"
CANARY_REFRESH = "CANARY_REFRESH_TOKEN_MARKER"
FIXED_STATE = "F" * 43
OTHER_FIXED_STATE = "G" * 43
TEST_AUTH_CODE = "ANspapi-oauth-code-placeholder-value"
TEST_REFRESH_TOKEN = "Atzr|oauth|refresh=token-placeholder"
def _unique_seller(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"[:32]


VALID_SELLER = "ValidOAuthSeller12345"

LWA_TOKEN_URL = "https://mock.lwa.local/auth/o2/token"
OAUTH_REDIRECT_URI = "https://api.oauth.test/api/v1/amazon/oauth/callback"


class FixedClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        self._current = current

    def __call__(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current = self._current + delta


class CountingLwaClient:
    def __init__(self, *, refresh_token: str = TEST_REFRESH_TOKEN, error: AmazonError | None = None) -> None:
        self.calls = 0
        self._refresh_token = refresh_token
        self._error = error

    async def exchange_authorization_code(self, code: str) -> LwaAuthorizationCodeResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return LwaAuthorizationCodeResponse(
            access_token="access-token-placeholder",
            refresh_token=self._refresh_token,
            token_type="bearer",
            expires_in=3600,
        )


class CountingAccountService(AmazonAccountService):
    connect_calls = 0
    reauthorize_calls = 0

    @classmethod
    def reset_counts(cls) -> None:
        cls.connect_calls = 0
        cls.reauthorize_calls = 0

    def connect_account_from_oauth(self, **kwargs):
        CountingAccountService.connect_calls += 1
        return super().connect_account_from_oauth(**kwargs)

    def reauthorize_account_from_oauth(self, **kwargs):
        CountingAccountService.reauthorize_calls += 1
        return super().reauthorize_account_from_oauth(**kwargs)


@pytest.fixture
def oauth_settings() -> AmazonSettings:
    return AmazonSettings(
        enabled=True,
        oauth_enabled=True,
        lwa_client_id=TEST_CLIENT_ID,
        lwa_client_secret=TEST_CLIENT_SECRET,
        lwa_token_url=LWA_TOKEN_URL,
        sp_api_region="na",
        endpoint_mode=AmazonEndpointMode.MOCK,
        user_agent="SellerAI-Copilot-Test/1.0.0 (Language=Python)",
        environment="testing",
        application_id="amzn1.sp.solution.test-app",
        oauth_redirect_uri=OAUTH_REDIRECT_URI,
        oauth_frontend_success_url="https://app.oauth.test/oauth/success",
        oauth_frontend_error_url="https://app.oauth.test/oauth/error",
        oauth_consent_version="beta",
    )


@pytest.fixture
def oauth_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


_created_user_ids: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
def cleanup_committed_oauth_service_rows(oauth_session_factory):
    _created_user_ids.clear()
    yield
    if not _created_user_ids:
        return
    session = oauth_session_factory()
    try:
        for user_id in _created_user_ids:
            session.query(AmazonOAuthState).filter_by(user_id=user_id).delete(synchronize_session=False)
            session.query(AmazonAccount).filter_by(user_id=user_id).delete(synchronize_session=False)
            session.query(User).filter_by(id=user_id).delete()
        session.commit()
    finally:
        session.close()
        _created_user_ids.clear()


def _account_service_factory(
    token_encryption_service: TokenEncryptionService,
    clock: FixedClock | None = None,
):
    def factory(db: Session) -> AmazonAccountService:
        return AmazonAccountService(
            db,
            token_encryption_service,
            clock=clock or FixedClock(datetime(2026, 4, 1, 12, 0, tzinfo=UTC)),
        )

    return factory


def _service(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    *,
    lwa_client: CountingLwaClient | None = None,
    clock: FixedClock | None = None,
    token_generator=None,
    account_service_factory=None,
) -> AmazonOAuthService:
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    fixed_clock = clock or FixedClock(datetime(2026, 4, 1, 12, 0, tzinfo=UTC))

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
            clock=fixed_clock,
            token_generator=token_generator,
        )

    lwa = lwa_client or CountingLwaClient()
    return AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=account_service_factory or _account_service_factory(
            token_encryption_service,
            fixed_clock,
        ),
        clock=fixed_clock,
    )


def _create_user(session_factory, email: str) -> User:
    session = session_factory()
    try:
        user = User(
            email=email,
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        _created_user_ids.append(user.id)
        return user
    finally:
        session.close()


def _lwa_transport_handler(status_code: int = 200, payload: dict[str, Any] | None = None):
    def handler(_request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"error": "invalid_grant"})
        return httpx.Response(status_code, json=payload or {
            "access_token": "access-token-placeholder",
            "refresh_token": TEST_REFRESH_TOKEN,
            "token_type": "bearer",
            "expires_in": 3600,
        })

    return handler


def test_connect_start_success(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-service-connect@example.com")
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
    )
    result = service.start_authorization(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    assert isinstance(result, AmazonOAuthStartResult)
    parsed = urlparse(result.authorization_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "sellercentral.amazon.com"
    assert parsed.path == AUTHORIZE_CONSENT_PATH
    query = parse_qs(parsed.query)
    assert query["application_id"] == [oauth_settings.application_id]
    raw_state = query["state"][0]
    assert raw_state
    assert query["version"] == ["beta"]
    assert result.marketplace_code == "US"
    assert result.region == "na"

    verify = oauth_session_factory()
    try:
        row = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert row.state_token_hash == hash_oauth_state_token(raw_state)
        assert row.status == OAuthStateStatus.PENDING
        for value in row.__dict__.values():
            assert raw_state not in str(value)
    finally:
        verify.close()


def test_reauthorize_start_success(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-service-reauth-start@example.com")
    account_session = oauth_session_factory()
    try:
        account_service = AmazonAccountService(account_session, token_encryption_service)
        summary = account_service.connect_account_from_oauth(
            user_id=user.id,
            region="na",
            selling_partner_id="ReauthStartSeller1",
            plaintext_refresh_token=TEST_REFRESH_TOKEN,
        )
        account_session.commit()
    finally:
        account_session.close()

    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        token_generator=lambda: OTHER_FIXED_STATE,
    )
    result = service.start_authorization(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.REAUTHORIZE,
        target_account_id=summary.id,
    )
    assert OTHER_FIXED_STATE in result.authorization_url
    assert result.region == "na"


def test_start_result_repr_hides_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-service-repr@example.com")
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        token_generator=lambda: CANARY_STATE,
    )
    result = service.start_authorization(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    rendered = repr(result)
    assert CANARY_STATE not in rendered
    assert result.authorization_url  # raw state only in URL field


@pytest.mark.parametrize(
    ("factory", "expected_code"),
    [(lambda: amazon_oauth_disabled_error(), AMAZON_OAUTH_DISABLED)],
)
def test_start_oauth_disabled(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    factory,
    expected_code: str,
) -> None:
    disabled = oauth_settings.model_copy(update={"oauth_enabled": False})
    user = _create_user(oauth_session_factory, f"oauth-disabled-{uuid.uuid4()}@example.com")
    service = _service(oauth_session_factory, disabled, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == expected_code


def test_start_invalid_marketplace(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-invalid-marketplace@example.com")
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=user.id,
            marketplace_code="ZZ",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_MARKETPLACE_INVALID


@pytest.mark.parametrize(
    ("intent", "target_account_id"),
    [
        (OAuthStateIntent.CONNECT, uuid.uuid4()),
        (OAuthStateIntent.REAUTHORIZE, None),
        ("invalid", None),
    ],
)
def test_start_invalid_intent_combination(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    intent: str,
    target_account_id: uuid.UUID | None,
) -> None:
    user = _create_user(oauth_session_factory, f"oauth-intent-{uuid.uuid4()}@example.com")
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=user.id,
            marketplace_code="US",
            intent=intent,
            target_account_id=target_account_id,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_INTENT_INVALID


def test_start_reauthorize_target_not_found(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-reauth-missing@example.com")
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.REAUTHORIZE,
            target_account_id=uuid.uuid4(),
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND


def test_start_reauthorize_target_other_user_is_tenant_safe(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    owner = _create_user(oauth_session_factory, "oauth-reauth-owner@example.com")
    other = _create_user(oauth_session_factory, "oauth-reauth-other@example.com")
    account_session = oauth_session_factory()
    try:
        account_service = AmazonAccountService(account_session, token_encryption_service)
        summary = account_service.connect_account_from_oauth(
            user_id=owner.id,
            region="na",
            selling_partner_id="ReauthOtherUserSeller1",
            plaintext_refresh_token=TEST_REFRESH_TOKEN,
        )
        account_session.commit()
    finally:
        account_session.close()

    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=other.id,
            marketplace_code="US",
            intent=OAuthStateIntent.REAUTHORIZE,
            target_account_id=summary.id,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND


def test_start_reauthorize_sandbox_target_rejected(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-reauth-sandbox@example.com")
    account_session = oauth_session_factory()
    try:
        account_service = AmazonAccountService(account_session, token_encryption_service)
        summary = account_service.create_account(
            user_id=user.id,
            region="na",
            endpoint_mode="sandbox",
            plaintext_refresh_token=TEST_REFRESH_TOKEN,
        )
        stored = account_session.get(AmazonAccount, summary.id)
        assert stored is not None
        stored.selling_partner_id = "SandboxTargetSeller1"
        account_session.commit()
    finally:
        account_session.close()

    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.REAUTHORIZE,
            target_account_id=summary.id,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_start_url_build_failure_rolls_back_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-url-fail@example.com")

    def _fail(**_kwargs):
        raise amazon_config_invalid_error("Amazon OAuth application id is invalid")

    monkeypatch.setattr(
        "app.services.amazon_oauth_service.build_seller_central_authorization_url",
        _fail,
    )
    session = oauth_session_factory()
    try:
        bound_service = _service(
            oauth_session_factory,
            oauth_settings,
            token_encryption_service,
        )
        with pytest.raises(AmazonError):
            bound_service.start_authorization(
                user_id=user.id,
                marketplace_code="US",
                intent=OAuthStateIntent.CONNECT,
            )
    finally:
        session.close()

    verify = oauth_session_factory()
    try:
        assert verify.query(AmazonOAuthState).filter_by(user_id=user.id).count() == 0
    finally:
        verify.close()


def test_start_success_leaves_no_open_transaction(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-start-tx@example.com")
    session = oauth_session_factory()
    try:
        from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

        def state_store_factory(db: Session) -> AmazonOAuthStateStore:
            return AmazonOAuthStateStore(
                db,
                ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
            )

        service = AmazonOAuthService(
            lambda: session,
            settings=oauth_settings,
            encryption_service=token_encryption_service,
            lwa_client_factory=lambda: CountingLwaClient(),
            state_store_factory=state_store_factory,
            account_service_factory=_account_service_factory(token_encryption_service),
        )
        service.start_authorization(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
        assert not session.in_transaction()
    finally:
        session.close()


async def _start_pending_state(
    service: AmazonOAuthService,
    *,
    user_id: uuid.UUID,
    intent: str = OAuthStateIntent.CONNECT,
    target_account_id: uuid.UUID | None = None,
) -> str:
    result = service.start_authorization(
        user_id=user_id,
        marketplace_code="US",
        intent=intent,
        target_account_id=target_account_id,
    )
    query = parse_qs(urlparse(result.authorization_url).query)
    return query["state"][0]


@pytest.mark.asyncio
async def test_callback_connect_success(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-callback-connect@example.com")
    lwa = CountingLwaClient()
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    seller_id = _unique_seller("Connect")
    raw_state = await _start_pending_state(service, user_id=user.id)
    result = await service.complete_authorization(
        state=raw_state,
        spapi_oauth_code=TEST_AUTH_CODE,
        selling_partner_id=seller_id,
    )
    assert result.endpoint_mode == OAUTH_ACCOUNT_ENDPOINT_MODE
    assert result.status == AmazonAccountStatus.ACTIVE
    assert lwa.calls == 1

    verify = oauth_session_factory()
    try:
        account = verify.query(AmazonAccount).filter_by(selling_partner_id=seller_id).one()
        assert account.user_id == user.id
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.CONSUMED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_reauthorize_success(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-callback-reauth@example.com")
    seller_id = _unique_seller("ReauthCb")
    account_session = oauth_session_factory()
    try:
        account_service = AmazonAccountService(account_session, token_encryption_service)
        summary = account_service.connect_account_from_oauth(
            user_id=user.id,
            region="na",
            selling_partner_id=seller_id,
            plaintext_refresh_token=TEST_REFRESH_TOKEN,
        )
        account_session.commit()
        account_id = summary.id
        account_key_before = account_session.get(AmazonAccount, account_id).account_key
    finally:
        account_session.close()

    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=CountingLwaClient(refresh_token="new-refresh-token-value"),
    )
    raw_state = await _start_pending_state(
        service,
        user_id=user.id,
        intent=OAuthStateIntent.REAUTHORIZE,
        target_account_id=account_id,
    )
    result = await service.complete_authorization(
        state=raw_state,
        spapi_oauth_code=TEST_AUTH_CODE,
        selling_partner_id=seller_id,
    )
    assert result.id == account_id

    verify = oauth_session_factory()
    try:
        stored = verify.get(AmazonAccount, account_id)
        assert stored is not None
        assert stored.account_key == account_key_before
        assert stored.selling_partner_id == seller_id
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_does_not_accept_client_identity_overrides(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    params = AmazonOAuthService.complete_authorization.__code__.co_varnames
    assert "state" in params
    assert "spapi_oauth_code" in params
    assert "selling_partner_id" in params
    assert "user_id" not in params
    assert "marketplace_code" not in params
    assert "redirect_uri" not in params
    assert "endpoint_mode" not in params


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_code"),
    [
        ("bad", AMAZON_OAUTH_STATE_INVALID),
        ("", AMAZON_OAUTH_STATE_INVALID),
    ],
)
async def test_callback_malformed_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    state: str,
    expected_code: str,
) -> None:
    lwa = CountingLwaClient()
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service, lwa_client=lwa)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == expected_code
    assert lwa.calls == 0


@pytest.mark.asyncio
async def test_callback_expired_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-callback-expired@example.com")
    clock = FixedClock(datetime(2026, 4, 1, 12, 0, tzinfo=UTC))
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        clock=clock,
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    clock.advance(timedelta(hours=2))
    lwa = CountingLwaClient()
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
        clock=clock,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_EXPIRED
    assert lwa.calls == 0


@pytest.mark.asyncio
async def test_callback_replay_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-callback-replay@example.com")
    lwa = CountingLwaClient()
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    seller_id = _unique_seller("Replay")
    raw_state = await _start_pending_state(service, user_id=user.id)
    await service.complete_authorization(
        state=raw_state,
        spapi_oauth_code=TEST_AUTH_CODE,
        selling_partner_id=seller_id,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=seller_id,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_REPLAY


@pytest.mark.asyncio
@pytest.mark.parametrize("seller_id", ["", "bad-seller", "x" * 33])
async def test_callback_invalid_seller_id(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    seller_id: str,
) -> None:
    lwa = CountingLwaClient()
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service, lwa_client=lwa)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state="bad",
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=seller_id,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_INVALID
    if seller_id:
        assert seller_id not in str(exc_info.value)
    assert lwa.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["", "   "])
async def test_callback_invalid_code(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    code: str,
) -> None:
    user = _create_user(oauth_session_factory, f"oauth-invalid-code-{uuid.uuid4()}@example.com")
    lwa = LwaTokenClient(
        settings=oauth_settings,
        transport=make_transport(_lwa_transport_handler()),
    )
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=code,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED
    verify = oauth_session_factory()
    try:
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.CONSUMED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_invalid_code_canary_not_logged(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-invalid-code-canary@example.com")
    lwa = LwaTokenClient(
        settings=oauth_settings,
        transport=make_transport(_lwa_transport_handler(status_code=400)),
    )
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=CANARY_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED
    assert CANARY_CODE not in caplog.text
    assert CANARY_CODE not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(400, AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED), (401, AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED), (403, AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED)],
)
async def test_callback_lwa_client_errors(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    status_code: int,
    expected_code: str,
) -> None:
    user = _create_user(oauth_session_factory, f"oauth-lwa-{status_code}@example.com")
    transport = make_transport(_lwa_transport_handler(status_code=status_code))
    lwa = LwaTokenClient(settings=oauth_settings, transport=transport)
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == expected_code


@pytest.mark.asyncio
async def test_callback_lwa_rate_limit(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-lwa-429@example.com")
    lwa = LwaTokenClient(
        settings=oauth_settings,
        transport=make_transport(_lwa_transport_handler(status_code=429)),
    )
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_LWA_RATE_LIMITED


@pytest.mark.asyncio
async def test_callback_lwa_unavailable(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-lwa-503@example.com")
    lwa = LwaTokenClient(
        settings=oauth_settings,
        transport=make_transport(_lwa_transport_handler(status_code=503)),
    )
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE


@pytest.mark.asyncio
async def test_callback_malformed_lwa_success_payload(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-lwa-malformed@example.com")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "only-access"})

    lwa = LwaTokenClient(settings=oauth_settings, transport=make_transport(handler))
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_callback_ownership_conflict(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    owner = _create_user(oauth_session_factory, "oauth-callback-owner@example.com")
    challenger = _create_user(oauth_session_factory, "oauth-callback-challenger@example.com")
    owner_session = oauth_session_factory()
    try:
        AmazonAccountService(owner_session, token_encryption_service).connect_account_from_oauth(
            user_id=owner.id,
            region="na",
            selling_partner_id="ConflictSeller1234",
            plaintext_refresh_token=TEST_REFRESH_TOKEN,
        )
        owner_session.commit()
    finally:
        owner_session.close()

    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
    )
    raw_state = await _start_pending_state(service, user_id=challenger.id)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id="ConflictSeller1234",
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_ALREADY_LINKED


@pytest.mark.asyncio
async def test_callback_reauthorize_seller_mismatch(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-callback-mismatch@example.com")
    account_session = oauth_session_factory()
    try:
        summary = AmazonAccountService(account_session, token_encryption_service).connect_account_from_oauth(
            user_id=user.id,
            region="na",
            selling_partner_id="MismatchSeller1234",
            plaintext_refresh_token=TEST_REFRESH_TOKEN,
        )
        account_session.commit()
    finally:
        account_session.close()

    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
    )
    raw_state = await _start_pending_state(
        service,
        user_id=user.id,
        intent=OAuthStateIntent.REAUTHORIZE,
        target_account_id=summary.id,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id="DifferentSeller12",
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_MISMATCH


@pytest.mark.asyncio
async def test_callback_state_consume_commit_failure_skips_lwa(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-consume-commit-fail@example.com")
    lwa = CountingLwaClient()
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    raw_state = await _start_pending_state(service, user_id=user.id)

    original_commit = Session.commit

    def _fail_commit(self) -> None:
        if self.is_active:
            raise RuntimeError("commit failed")

    monkeypatch.setattr(Session, "commit", _fail_commit)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_INVALID
    assert lwa.calls == 0
    monkeypatch.setattr(Session, "commit", original_commit)


@pytest.mark.asyncio
async def test_callback_lwa_failure_leaves_state_consumed(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-lwa-fail-consumed@example.com")
    lwa = CountingLwaClient(error=amazon_oauth_token_exchange_failed_error())
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    raw_state = await _start_pending_state(service, user_id=user.id)
    with pytest.raises(AmazonError):
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    verify = oauth_session_factory()
    try:
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.CONSUMED
        assert verify.query(AmazonAccount).filter_by(user_id=user.id).count() == 0
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_persistence_failure_leaves_state_consumed(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-persist-fail-consumed@example.com")
    lwa = CountingLwaClient()
    service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    raw_state = await _start_pending_state(service, user_id=user.id)

    def _fail_connect(self, **_kwargs):
        raise amazon_oauth_account_persist_failed_error()

    monkeypatch.setattr(AmazonAccountService, "connect_account_from_oauth", _fail_connect)
    with pytest.raises(AmazonError) as exc_info:
        await service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED
    verify = oauth_session_factory()
    try:
        assert verify.query(AmazonOAuthState).filter_by(user_id=user.id).one().status == OAuthStateStatus.CONSUMED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_success_leaves_no_open_transaction(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-callback-tx@example.com")
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    tracked_sessions: list[Session] = []

    def tracking_session_factory() -> Session:
        session = oauth_session_factory()
        tracked_sessions.append(session)
        return session

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    service = AmazonOAuthService(
        tracking_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: CountingLwaClient(),
        state_store_factory=state_store_factory,
        account_service_factory=_account_service_factory(token_encryption_service),
    )
    seller_id = _unique_seller("CallbackTx")
    raw_state = await _start_pending_state(service, user_id=user.id)
    await service.complete_authorization(
        state=raw_state,
        spapi_oauth_code=TEST_AUTH_CODE,
        selling_partner_id=seller_id,
    )
    assert tracked_sessions
    for session in tracked_sessions:
        assert not session.in_transaction()
        session.close()


def test_start_user_not_found(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.start_authorization(
            user_id=uuid.uuid4(),
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_USER_NOT_FOUND


@pytest.mark.asyncio
async def test_callback_repr_and_logs_hide_canaries(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _service(oauth_session_factory, oauth_settings, token_encryption_service)
    with pytest.raises(AmazonError):
        await service.complete_authorization(
            state="bad",
            spapi_oauth_code=CANARY_CODE,
            selling_partner_id=CANARY_SELLER,
        )
    assert CANARY_CODE not in caplog.text
    assert CANARY_SELLER not in caplog.text
    assert CANARY_REFRESH not in caplog.text


def test_missing_lwa_dependency_does_not_consume_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    with pytest.raises(TypeError):
        AmazonOAuthService(
            oauth_session_factory,
            settings=oauth_settings,
            encryption_service=token_encryption_service,
            account_service_factory=_account_service_factory(token_encryption_service),
        )


@pytest.mark.asyncio
async def test_missing_lwa_dependency_keeps_existing_state_pending(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-missing-lwa-state@example.com")
    lwa = CountingLwaClient()
    start_service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    raw_state = await _start_pending_state(start_service, user_id=user.id)
    assert raw_state
    assert lwa.calls == 0

    verify = oauth_session_factory()
    try:
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.PENDING
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_missing_account_service_dependency_does_not_consume_state(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    user = _create_user(oauth_session_factory, "oauth-missing-account-factory@example.com")
    lwa = CountingLwaClient()
    start_service = _service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa,
    )
    raw_state = await _start_pending_state(start_service, user_id=user.id)

    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    broken_service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=None,
    )
    with pytest.raises(AmazonError) as exc_info:
        await broken_service.complete_authorization(
            state=raw_state,
            spapi_oauth_code=TEST_AUTH_CODE,
            selling_partner_id=VALID_SELLER,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID
    assert TEST_CLIENT_SECRET not in str(exc_info.value)
    assert lwa.calls == 0
    CountingAccountService.reset_counts()

    verify = oauth_session_factory()
    try:
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.PENDING
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_callback_lwa_transport_failure_leaves_state_consumed(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    CountingAccountService.reset_counts()
    user = _create_user(oauth_session_factory, f"oauth-transport-fail-{uuid.uuid4()}@example.com")

    class NetworkFailureTransport:
        async def request(self, *_args: object, **_kwargs: object) -> None:
            raise TransportError(
                kind=TransportFailureKind.NETWORK,
                message="network CANARY_OAUTH_CODE_SECRET_MARKER",
            )

    lwa = LwaTokenClient(settings=oauth_settings, transport=NetworkFailureTransport())
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    def counting_account_factory(db: Session) -> AmazonAccountService:
        return CountingAccountService(
            db,
            token_encryption_service,
            clock=FixedClock(datetime(2026, 4, 1, 12, 0, tzinfo=UTC)),
        )

    start_service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=counting_account_factory,
    )
    raw_state = await _start_pending_state(start_service, user_id=user.id)

    tracked_sessions: list[Session] = []

    def tracking_session_factory() -> Session:
        session = oauth_session_factory()
        tracked_sessions.append(session)
        return session

    callback_service = AmazonOAuthService(
        tracking_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=counting_account_factory,
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await callback_service.complete_authorization(
                state=raw_state,
                spapi_oauth_code=CANARY_CODE,
                selling_partner_id=CANARY_SELLER,
            )
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE
    assert CANARY_CODE not in str(exc_info.value)
    assert CANARY_SELLER not in str(exc_info.value)
    assert CANARY_CODE not in caplog.text
    assert CANARY_SELLER not in caplog.text
    assert CountingAccountService.connect_calls == 0
    assert CountingAccountService.reauthorize_calls == 0

    verify = oauth_session_factory()
    try:
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.CONSUMED
    finally:
        verify.close()

    for session in tracked_sessions:
        assert not session.in_transaction()
        session.close()


@pytest.mark.asyncio
async def test_callback_lwa_timeout_failure_leaves_state_consumed(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    CountingAccountService.reset_counts()
    user = _create_user(oauth_session_factory, f"oauth-timeout-fail-{uuid.uuid4()}@example.com")

    def timeout_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout CANARY_OAUTH_CODE_SECRET_MARKER")

    lwa = LwaTokenClient(settings=oauth_settings, transport=make_transport(timeout_handler))
    from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
        )

    def counting_account_factory(db: Session) -> AmazonAccountService:
        return CountingAccountService(
            db,
            token_encryption_service,
            clock=FixedClock(datetime(2026, 4, 1, 12, 0, tzinfo=UTC)),
        )

    start_service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=counting_account_factory,
    )
    raw_state = await _start_pending_state(start_service, user_id=user.id)

    callback_service = AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa,
        state_store_factory=state_store_factory,
        account_service_factory=counting_account_factory,
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await callback_service.complete_authorization(
                state=raw_state,
                spapi_oauth_code=CANARY_CODE,
                selling_partner_id=CANARY_SELLER,
            )
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE
    assert CANARY_CODE not in caplog.text
    assert CountingAccountService.connect_calls == 0

    verify = oauth_session_factory()
    try:
        state = verify.query(AmazonOAuthState).filter_by(user_id=user.id).one()
        assert state.status == OAuthStateStatus.CONSUMED
    finally:
        verify.close()
