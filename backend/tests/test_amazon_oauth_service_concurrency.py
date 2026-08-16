"""Amazon OAuth orchestration concurrent callback tests."""

from __future__ import annotations

import asyncio
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import get_password_hash
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_OAUTH_STATE_REPLAY,
    AmazonError,
)
from app.integrations.amazon.lwa import LwaAuthorizationCodeResponse
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount
from app.models.amazon_oauth_state import AmazonOAuthState, OAuthStateIntent, OAuthStateStatus
from app.models.user import User
from app.services.amazon_account_service import AmazonAccountService, AmazonAccountSummary
from app.services.amazon_oauth_service import AmazonOAuthService
from app.services.amazon_oauth_state_store import AmazonOAuthStateStore
from tests.integrations.amazon.conftest import TEST_CLIENT_ID, TEST_CLIENT_SECRET

CALLBACK_TIMEOUT_SECONDS = 20
TEST_AUTH_CODE = "ANspapi-oauth-code-placeholder-value"
TEST_REFRESH_TOKEN = "Atzr|oauth|refresh=token-placeholder"
LWA_TOKEN_URL = "https://mock.lwa.local/auth/o2/token"
OAUTH_REDIRECT_URI = "https://api.oauth.test/api/v1/amazon/oauth/callback"


def _unique_seller(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"[:32]


class FixedClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        self._current = current

    def __call__(self) -> datetime:
        return self._current


class CountingLwaClient:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    async def exchange_authorization_code(self, code: str) -> LwaAuthorizationCodeResponse:
        with self._lock:
            self.calls += 1
        return LwaAuthorizationCodeResponse(
            access_token="access-token-placeholder",
            refresh_token=TEST_REFRESH_TOKEN,
            token_type="bearer",
            expires_in=3600,
        )


class CountingAccountService(AmazonAccountService):
    connect_calls = 0
    reauthorize_calls = 0
    _count_lock = threading.Lock()
    _consume_barrier: threading.Barrier | None = None

    @classmethod
    def reset_counts(cls) -> None:
        with cls._count_lock:
            cls.connect_calls = 0
            cls.reauthorize_calls = 0

    @classmethod
    def set_consume_barrier(cls, barrier: threading.Barrier | None) -> None:
        cls._consume_barrier = barrier

    def connect_account_from_oauth(self, **kwargs):
        with self._count_lock:
            CountingAccountService.connect_calls += 1
        return super().connect_account_from_oauth(**kwargs)

    def reauthorize_account_from_oauth(self, **kwargs):
        with self._count_lock:
            CountingAccountService.reauthorize_calls += 1
        return super().reauthorize_account_from_oauth(**kwargs)


@pytest.fixture
def oauth_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


_created_user_ids: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
def cleanup_committed_oauth_service_concurrency_rows(oauth_session_factory):
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


def _build_service(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
    *,
    lwa_client: CountingLwaClient,
    state_token: str,
    consume_barrier: threading.Barrier | None = None,
) -> AmazonOAuthService:
    clock = FixedClock(datetime(2026, 5, 1, 12, 0, tzinfo=UTC))
    CountingAccountService.set_consume_barrier(consume_barrier)

    def state_store_factory(db: Session) -> AmazonOAuthStateStore:
        store = AmazonOAuthStateStore(
            db,
            ttl_seconds=oauth_settings.oauth_state_ttl_seconds,
            clock=clock,
            token_generator=lambda: state_token,
        )
        if consume_barrier is not None:
            original_consume = store.consume_state

            def synchronized_consume(raw_state: str):
                consume_barrier.wait(timeout=CALLBACK_TIMEOUT_SECONDS)
                return original_consume(raw_state)

            store.consume_state = synchronized_consume  # type: ignore[method-assign]
        return store

    def account_service_factory(db: Session) -> AmazonAccountService:
        return CountingAccountService(db, token_encryption_service, clock=clock)

    return AmazonOAuthService(
        oauth_session_factory,
        settings=oauth_settings,
        encryption_service=token_encryption_service,
        lwa_client_factory=lambda: lwa_client,
        state_store_factory=state_store_factory,
        account_service_factory=account_service_factory,
        clock=clock,
    )


def test_concurrent_callback_single_winner(
    oauth_session_factory,
    oauth_settings: AmazonSettings,
    token_encryption_service: TokenEncryptionService,
) -> None:
    CountingAccountService.reset_counts()
    create_session = oauth_session_factory()
    try:
        user = User(
            email=f"oauth-service-concurrency-{uuid.uuid4()}@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        create_session.add(user)
        create_session.commit()
        user_id = user.id
        seller_id = _unique_seller("Concurrent")
        _created_user_ids.append(user_id)
    finally:
        create_session.close()

    lwa_client = CountingLwaClient()
    state_token = secrets.token_urlsafe(32)
    service = _build_service(
        oauth_session_factory,
        oauth_settings,
        token_encryption_service,
        lwa_client=lwa_client,
        state_token=state_token,
    )
    start = service.start_authorization(
        user_id=user_id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    raw_state = parse_qs(urlparse(start.authorization_url).query)["state"][0]

    consume_barrier = threading.Barrier(2, timeout=CALLBACK_TIMEOUT_SECONDS)
    results: list[AmazonAccountSummary | AmazonError] = []

    async def _run_callback() -> None:
        worker_service = _build_service(
            oauth_session_factory,
            oauth_settings,
            token_encryption_service,
            lwa_client=lwa_client,
            state_token=state_token,
            consume_barrier=consume_barrier,
        )
        try:
            summary = await worker_service.complete_authorization(
                state=raw_state,
                spapi_oauth_code=TEST_AUTH_CODE,
                selling_partner_id=seller_id,
            )
            results.append(summary)
        except AmazonError as exc:
            results.append(exc)

    def _worker() -> None:
        asyncio.run(_run_callback())

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_worker) for _ in range(2)]
        for future in as_completed(futures, timeout=CALLBACK_TIMEOUT_SECONDS):
            future.result(timeout=CALLBACK_TIMEOUT_SECONDS)

    successes = [result for result in results if isinstance(result, AmazonAccountSummary)]
    failures = [result for result in results if isinstance(result, AmazonError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].error_code == AMAZON_OAUTH_STATE_REPLAY
    assert lwa_client.calls == 1
    assert CountingAccountService.connect_calls == 1
    assert CountingAccountService.reauthorize_calls == 0

    verify = oauth_session_factory()
    try:
        assert (
            verify.query(AmazonAccount)
            .filter_by(selling_partner_id=seller_id, user_id=user_id)
            .count()
            == 1
        )
        state = verify.query(AmazonOAuthState).filter_by(user_id=user_id).one()
        assert state.status == OAuthStateStatus.CONSUMED
    finally:
        verify.close()
