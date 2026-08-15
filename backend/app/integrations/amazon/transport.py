"""HTTP transport abstraction for Amazon integrations."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TRANSPORT_TIMEOUT = 30.0
# A1 generic JSON response protection. Large binary/report downloads must use a
# dedicated streaming download client, not this in-memory transport.
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
READ_CHUNK_SIZE = 8192


class TransportFailureKind(str, Enum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROTOCOL = "protocol"


class TransportError(Exception):
    """Domain-agnostic HTTP transport failure (mapped by LWA/SP-API clients)."""

    def __init__(
        self,
        *,
        kind: TransportFailureKind,
        message: str = "HTTP transport failed",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.cause = None


class ResponseTooLargeError(Exception):
    """Response body exceeded configured byte limit during streaming read."""

    def __init__(self, *, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__("Response exceeded size limit")


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if not self.content:
            return None
        return json.loads(self.content)


class HttpTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        timeout: float = DEFAULT_TRANSPORT_TIMEOUT,
    ) -> HttpResponse: ...


class HttpxTransport:
    """httpx-backed transport; accepts an injected AsyncClient or MockTransport."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        default_timeout: float = DEFAULT_TRANSPORT_TIMEOUT,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._default_timeout = default_timeout
        self._max_response_bytes = max_response_bytes

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        data: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        effective_timeout = self._default_timeout if timeout is None else timeout
        client = self._client or httpx.AsyncClient(follow_redirects=False)
        failure_kind: TransportFailureKind | None = None
        try:
            async with client.stream(
                method,
                url,
                headers=dict(headers or {}),
                params=dict(params or {}) or None,
                data=dict(data or {}) or None,
                json=json_body,
                timeout=effective_timeout,
                follow_redirects=False,
            ) as response:
                content = await _read_bounded_response(
                    response,
                    max_bytes=self._max_response_bytes,
                )
                return HttpResponse(
                    status_code=response.status_code,
                    content=content,
                    headers={k.lower(): v for k, v in response.headers.items()},
                )
        except ResponseTooLargeError:
            logger.warning("HTTP response exceeded size limit")
            raise
        except httpx.TimeoutException:
            logger.warning("HTTP transport timeout method=%s", method)
            failure_kind = TransportFailureKind.TIMEOUT
        except httpx.HTTPError:
            logger.warning("HTTP transport failure method=%s", method)
            failure_kind = TransportFailureKind.NETWORK
        finally:
            if self._owns_client:
                await client.aclose()

        if failure_kind is not None:
            raise TransportError(kind=failure_kind)


async def _read_bounded_response(response: httpx.Response, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes(READ_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(max_bytes=max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)
