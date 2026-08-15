"""In-memory access token cache for Amazon LWA tokens."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

Clock = Callable[[], float]


@dataclass(frozen=True)
class CachedAccessToken:
    access_token: str
    expires_at: float

    @classmethod
    def from_token(
        cls,
        *,
        access_token: str,
        expires_in: int,
        now: float | None = None,
        clock: Clock | None = None,
    ) -> CachedAccessToken:
        current = now if now is not None else (clock or time.time)()
        return cls(
            access_token=access_token,
            expires_at=current + expires_in,
        )

    def is_expired(
        self,
        *,
        skew_seconds: int = 0,
        now: float | None = None,
        clock: Clock | None = None,
    ) -> bool:
        current = now if now is not None else (clock or time.time)()
        return current >= (self.expires_at - skew_seconds)


class TokenCache(Protocol):
    def get(self, key: str) -> CachedAccessToken | None: ...

    def set(self, key: str, token: CachedAccessToken) -> None: ...

    def invalidate(self, key: str) -> None: ...


class InMemoryTokenCache:
    """Process-local token cache keyed by account_key (never by token value)."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._store: dict[str, CachedAccessToken] = {}
        self._clock = clock or time.time

    def get(self, key: str) -> CachedAccessToken | None:
        return self._store.get(key)

    def set(self, key: str, token: CachedAccessToken) -> None:
        self._store[key] = token

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    @property
    def clock(self) -> Clock:
        return self._clock


Factory = Callable[[], Coroutine[Any, Any, Any]]


def _consume_task_result(task: asyncio.Task[Any]) -> None:
    """Retrieve task outcome so done tasks never leave orphan exceptions."""
    if task.cancelled():
        return
    task.exception()


class SingleFlightCoordinator:
    """Ensure one in-flight refresh per key; shield waiters from shared task cancel."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[Any]] = {}

    async def run(self, key: str, factory: Factory) -> Any:
        async with self._lock:
            task = self._inflight.get(key)
            if task is not None and task.done():
                _consume_task_result(task)
                self._inflight.pop(key, None)
                task = None
            if task is None:
                task = asyncio.create_task(factory())
                self._inflight[key] = task

                def _on_done(completed: asyncio.Task[Any]) -> None:
                    self._on_task_done(key, completed)

                task.add_done_callback(_on_done)

        return await asyncio.shield(task)

    def _on_task_done(self, key: str, task: asyncio.Task[Any]) -> None:
        _consume_task_result(task)
        self._schedule_cleanup(key, task)

    def _schedule_cleanup(self, key: str, task: asyncio.Task[Any]) -> None:
        async def _cleanup() -> None:
            async with self._lock:
                if self._inflight.get(key) is task:
                    self._inflight.pop(key, None)

        try:
            asyncio.get_running_loop().create_task(_cleanup())
        except RuntimeError:
            return

    @property
    def inflight_keys(self) -> frozenset[str]:
        return frozenset(self._inflight)
