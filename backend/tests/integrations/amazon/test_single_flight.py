from __future__ import annotations

import asyncio

import pytest

from app.integrations.amazon.token_cache import SingleFlightCoordinator, _consume_task_result


async def _wait_until(condition, *, timeout: float = 1.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if condition():
            return
        await asyncio.sleep(0)
    raise TimeoutError("condition not met within timeout")


@pytest.mark.asyncio
async def test_single_flight_waiter_cancel_does_not_cancel_shared_task():
    factory_calls = 0
    gate = asyncio.Event()

    async def factory() -> str:
        nonlocal factory_calls
        factory_calls += 1
        await gate.wait()
        return "shared-result"

    coord = SingleFlightCoordinator()

    async def waiter() -> str:
        return await coord.run("acct-1", factory)

    task1 = asyncio.create_task(waiter())
    task2 = asyncio.create_task(waiter())
    task3 = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    task2.cancel()
    gate.set()

    result1 = await task1
    result3 = await task3
    with pytest.raises(asyncio.CancelledError):
        await task2

    assert result1 == result3 == "shared-result"
    assert factory_calls == 1
    assert coord.inflight_keys == frozenset()


@pytest.mark.asyncio
async def test_single_flight_factory_exception_propagates_to_all_waiters():
    coord = SingleFlightCoordinator()

    async def factory() -> None:
        raise ValueError("refresh failed")

    results = await asyncio.gather(
        coord.run("acct-1", factory),
        coord.run("acct-1", factory),
        return_exceptions=True,
    )
    assert all(isinstance(item, ValueError) for item in results)
    assert str(results[0]) == "refresh failed"
    assert coord.inflight_keys == frozenset()


@pytest.mark.asyncio
async def test_single_flight_retry_after_failure():
    coord = SingleFlightCoordinator()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return "ok"

    with pytest.raises(RuntimeError):
        await coord.run("acct-1", factory)
    assert coord.inflight_keys == frozenset()
    assert await coord.run("acct-1", factory) == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_single_flight_shared_task_cancel_cleans_inflight():
    coord = SingleFlightCoordinator()
    gate = asyncio.Event()

    async def factory() -> str:
        await gate.wait()
        return "ok"

    waiter_task = asyncio.create_task(coord.run("acct-1", factory))
    await asyncio.sleep(0)
    async with coord._lock:
        shared = coord._inflight["acct-1"]
    shared.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    await asyncio.sleep(0)
    assert coord.inflight_keys == frozenset()


@pytest.mark.asyncio
async def test_single_flight_different_keys_run_concurrently():
    coord = SingleFlightCoordinator()
    started: dict[str, asyncio.Event] = {
        "a": asyncio.Event(),
        "b": asyncio.Event(),
    }
    releases: dict[str, asyncio.Event] = {
        "a": asyncio.Event(),
        "b": asyncio.Event(),
    }

    async def factory(key: str) -> str:
        started[key].set()
        await releases[key].wait()
        return key

    task_a = asyncio.create_task(coord.run("a", lambda: factory("a")))
    task_b = asyncio.create_task(coord.run("b", lambda: factory("b")))
    await asyncio.wait_for(started["a"].wait(), timeout=1)
    await asyncio.wait_for(started["b"].wait(), timeout=1)
    releases["a"].set()
    releases["b"].set()
    assert await task_a == "a"
    assert await task_b == "b"


@pytest.mark.asyncio
async def test_single_flight_orphan_exception_consumed_when_waiter_cancelled():
    loop = asyncio.get_running_loop()
    loop_messages: list[str] = []

    def exception_handler(_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        message = str(context.get("message", ""))
        loop_messages.append(message)

    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(exception_handler)

    coord = SingleFlightCoordinator()
    gate = asyncio.Event()
    factory_started = asyncio.Event()

    async def factory() -> str:
        factory_started.set()
        await gate.wait()
        raise ValueError("factory failed after waiter cancel")

    waiter_task = asyncio.create_task(coord.run("shared-key", factory))
    await asyncio.wait_for(factory_started.wait(), timeout=1)
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    gate.set()
    await asyncio.wait_for(_wait_until(lambda: not coord.inflight_keys), timeout=1)

    assert coord.inflight_keys == frozenset()
    assert not any("Task exception was never retrieved" in msg for msg in loop_messages)
    loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_single_flight_replaces_done_task_before_stale_callback_runs():
    calls = 0
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    second_factory_started = asyncio.Event()

    class DelayedCleanupCoordinator(SingleFlightCoordinator):
        def __init__(self) -> None:
            super().__init__()
            self._cleanup_tasks: list[asyncio.Task[None]] = []

        def _schedule_cleanup(self, key: str, task: asyncio.Task[object]) -> None:
            async def _cleanup() -> None:
                cleanup_started.set()
                await release_cleanup.wait()
                async with self._lock:
                    if self._inflight.get(key) is task:
                        self._inflight.pop(key, None)

            cleanup_task = asyncio.get_running_loop().create_task(_cleanup())
            self._cleanup_tasks.append(cleanup_task)

    coord = DelayedCleanupCoordinator()

    async def factory() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first failure")
        second_factory_started.set()
        return "second-success"

    with pytest.raises(RuntimeError, match="first failure"):
        await coord.run("race-key", factory)

    second = asyncio.create_task(coord.run("race-key", factory))
    await asyncio.wait_for(cleanup_started.wait(), timeout=1)
    await asyncio.wait_for(second_factory_started.wait(), timeout=1)
    assert calls == 2

    result = await asyncio.wait_for(second, timeout=1)
    assert result == "second-success"
    assert coord.inflight_keys == frozenset({"race-key"})

    release_cleanup.set()
    await asyncio.wait_for(asyncio.gather(*coord._cleanup_tasks), timeout=1)
    assert coord.inflight_keys == frozenset()


@pytest.mark.asyncio
async def test_consume_task_result_skips_cancelled_task():
    async def _noop() -> None:
        return None

    task = asyncio.create_task(_noop())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _consume_task_result(task)
