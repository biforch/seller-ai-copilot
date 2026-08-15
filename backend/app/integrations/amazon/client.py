"""Amazon SP-API HTTP client."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.integrations.amazon.config import AmazonSettings
from app.integrations.amazon.constants import resolve_sp_api_base_url
from app.integrations.amazon.exceptions import (
    AmazonError,
    amazon_disabled_error,
    amazon_response_invalid_error,
    amazon_response_too_large_error,
    sp_api_error_from_status,
    sp_api_transport_error,
)
from app.integrations.amazon.lwa import TokenProvider, normalize_account_key
from app.integrations.amazon.transport import (
    HttpResponse,
    HttpTransport,
    HttpxTransport,
    ResponseTooLargeError,
    TransportError,
)

logger = logging.getLogger(__name__)

_ABSOLUTE_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_REQUEST_ID_HEADER = "x-amzn-requestid"


@dataclass(frozen=True)
class SpApiResponse:
    status_code: int
    headers: dict[str, str]
    payload: Any

    @property
    def text(self) -> str:
        if self.payload is None:
            return ""
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


def validate_sp_api_path(path: str) -> None:
    from app.integrations.amazon.exceptions import amazon_config_invalid_error

    if not path.startswith("/"):
        raise amazon_config_invalid_error("SP-API path must start with '/'")
    if path.startswith("//"):
        raise amazon_config_invalid_error("SP-API path must not be scheme-relative")
    if _ABSOLUTE_URL_RE.match(path):
        raise amazon_config_invalid_error("SP-API path must be relative, not an absolute URL")


def utc_amz_date(*, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    return current.strftime("%Y%m%dT%H%M%SZ")


def build_sp_api_headers(
    *,
    access_token: str,
    user_agent: str,
    host: str,
    amz_date: str | None = None,
) -> dict[str, str]:
    return {
        "host": host,
        "x-amz-access-token": access_token,
        "user-agent": user_agent,
        "x-amz-date": amz_date or utc_amz_date(),
        "content-type": "application/json",
    }


class SpApiClient:
    """Minimal SP-API client: LWA access token + regional endpoint + standard headers."""

    def __init__(
        self,
        *,
        settings: AmazonSettings,
        transport: HttpTransport | None = None,
        token_provider: TokenProvider,
        amz_date_factory: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or HttpxTransport()
        self._token_provider = token_provider
        self._amz_date_factory = amz_date_factory or utc_amz_date

    @property
    def base_url(self) -> str:
        return resolve_sp_api_base_url(
            region=self._settings.region,
            endpoint_mode=self._settings.endpoint_mode.value,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        account_key: str,
        params: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        timeout: float = 30.0,
    ) -> SpApiResponse:
        if not self._settings.enabled:
            raise amazon_disabled_error()

        validate_sp_api_path(path)
        key = normalize_account_key(account_key)

        access_token = await self._token_provider.get_access_token(account_key=key)
        base = self.base_url.rstrip("/")
        url = f"{base}{path}"
        host = base.removeprefix("https://").removeprefix("http://")
        headers = build_sp_api_headers(
            access_token=access_token,
            user_agent=self._settings.user_agent,
            host=host,
            amz_date=self._amz_date_factory(),
        )

        try:
            response = await self._transport.request(
                method,
                url,
                headers=headers,
                params=params,
                json_body=json_body,
                timeout=timeout,
            )
        except ResponseTooLargeError as exc:
            logger.warning("SP-API response exceeded size limit path=%s", path)
            raise amazon_response_too_large_error() from exc
        except TransportError as exc:
            logger.warning(
                "SP-API transport failed method=%s path=%s",
                method,
                path,
            )
            raise sp_api_transport_error(cause=exc.cause or exc) from exc
        except AmazonError:
            raise
        except Exception as exc:
            logger.warning(
                "SP-API transport failed method=%s path=%s",
                method,
                path,
            )
            raise sp_api_transport_error(cause=exc) from exc

        return self._to_sp_api_response(response, path=path)

    def _to_sp_api_response(self, response: HttpResponse, *, path: str) -> SpApiResponse:
        request_id = response.headers.get(_REQUEST_ID_HEADER)

        if response.status_code >= 400:
            logger.warning(
                "SP-API error status=%s path=%s request_id=%s",
                response.status_code,
                path,
                request_id or "-",
            )
            raise sp_api_error_from_status(response.status_code, request_id=request_id)

        payload: Any
        if not response.content:
            payload = None
        else:
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    payload = response.json()
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "SP-API invalid JSON path=%s request_id=%s",
                        path,
                        request_id or "-",
                    )
                    raise amazon_response_invalid_error(cause=exc) from exc
            else:
                payload = response.text

        return SpApiResponse(
            status_code=response.status_code,
            headers=response.headers,
            payload=payload,
        )
