"""Login with Amazon (LWA) token exchange."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from app.integrations.amazon.config import AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_LWA_TOKEN_INVALID,
    AmazonError,
    amazon_config_invalid_error,
    amazon_response_invalid_error,
    amazon_response_too_large_error,
    lwa_error_from_status,
    lwa_unavailable_error,
)
from app.integrations.amazon.token_cache import (
    CachedAccessToken,
    InMemoryTokenCache,
    SingleFlightCoordinator,
    TokenCache,
)
from app.integrations.amazon.transport import (
    HttpTransport,
    HttpxTransport,
    ResponseTooLargeError,
    TransportError,
)

logger = logging.getLogger(__name__)

RefreshTokenResolver = Callable[[str], Awaitable[str | None]]


def normalize_account_key(account_key: str) -> str:
    normalized = account_key.strip()
    if not normalized:
        raise amazon_config_invalid_error("Account key is required")
    return normalized


class LwaTokenResponse(BaseModel):
    access_token: str = Field(min_length=1)
    token_type: str
    expires_in: int = Field(ge=1)
    refresh_token: str | None = None


class LwaTokenClient:
    """Exchange LWA refresh tokens or client credentials for access tokens."""

    def __init__(
        self,
        *,
        settings: AmazonSettings,
        transport: HttpTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or HttpxTransport()

    async def exchange_refresh_token(self, refresh_token: str) -> LwaTokenResponse:
        token = refresh_token.strip()
        if not token:
            raise AmazonError(
                "Refresh token is required",
                error_code=AMAZON_LWA_TOKEN_INVALID,
            )
        return await self._exchange_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": token,
                "client_id": self._settings.lwa_client_id,
                "client_secret": self._settings.lwa_client_secret,
            }
        )

    async def exchange_client_credentials(self, scope: str) -> LwaTokenResponse:
        return await self._exchange_token(
            {
                "grant_type": "client_credentials",
                "scope": scope,
                "client_id": self._settings.lwa_client_id,
                "client_secret": self._settings.lwa_client_secret,
            }
        )

    async def _exchange_token(self, form: dict[str, str]) -> LwaTokenResponse:
        try:
            response = await self._transport.request(
                "POST",
                self._settings.lwa_token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                data=form,
            )
        except ResponseTooLargeError as exc:
            logger.warning("LWA response exceeded size limit")
            raise amazon_response_too_large_error() from exc
        except TransportError as exc:
            logger.warning("LWA token request failed")
            raise lwa_unavailable_error(cause=exc.cause or exc) from exc
        except AmazonError:
            raise
        except Exception as exc:
            logger.warning("LWA token request failed")
            raise lwa_unavailable_error(cause=exc) from exc

        if response.status_code != 200:
            logger.warning(
                "LWA token exchange returned status=%s",
                response.status_code,
            )
            raise lwa_error_from_status(response.status_code)

        try:
            payload = response.json()
            return LwaTokenResponse.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            logger.warning("LWA token response validation failed")
            raise amazon_response_invalid_error(cause=exc) from exc
        except Exception as exc:
            logger.warning("LWA token response parse failed")
            raise amazon_response_invalid_error(cause=exc) from exc


class TokenProvider(Protocol):
    async def get_access_token(self, *, account_key: str) -> str: ...


class CachingRefreshTokenProvider:
    """Resolve refresh token per account, cache access tokens with single-flight refresh."""

    def __init__(
        self,
        *,
        client: LwaTokenClient,
        cache: TokenCache | None = None,
        refresh_token_resolver: RefreshTokenResolver,
        expiry_skew_seconds: int = 60,
        single_flight: SingleFlightCoordinator | None = None,
    ) -> None:
        self._client = client
        self._cache = cache or InMemoryTokenCache()
        self._refresh_token_resolver = refresh_token_resolver
        self._expiry_skew_seconds = expiry_skew_seconds
        self._single_flight = single_flight or SingleFlightCoordinator()

    def _clock(self):
        if isinstance(self._cache, InMemoryTokenCache):
            return self._cache.clock
        return None

    async def get_access_token(self, *, account_key: str) -> str:
        key = normalize_account_key(account_key)
        clock = self._clock()
        now = clock() if clock else None

        cached = self._cache.get(key)
        if cached is not None and not cached.is_expired(
            skew_seconds=self._expiry_skew_seconds,
            now=now,
            clock=clock,
        ):
            return cached.access_token

        return await self._single_flight.run(
            key,
            lambda: self._refresh_access_token(key),
        )

    async def _refresh_access_token(self, account_key: str) -> str:
        clock = self._clock()
        now = clock() if clock else None

        cached = self._cache.get(account_key)
        if cached is not None and not cached.is_expired(
            skew_seconds=self._expiry_skew_seconds,
            now=now,
            clock=clock,
        ):
            return cached.access_token

        refresh_token = await self._refresh_token_resolver(account_key)
        if refresh_token is None or not refresh_token.strip():
            raise AmazonError(
                "No refresh token available for account",
                error_code=AMAZON_LWA_TOKEN_INVALID,
            )

        token_response = await self._client.exchange_refresh_token(refresh_token)
        cached_token = CachedAccessToken.from_token(
            access_token=token_response.access_token,
            expires_in=token_response.expires_in,
            now=now,
            clock=clock,
        )
        self._cache.set(account_key, cached_token)
        return cached_token.access_token


RefreshTokenProvider = CachingRefreshTokenProvider
