"""Fixtures shared by every end-to-end test.

This tier drives the real CLI through `CliRunner` and fakes only the provider
boundary: Microsoft Graph with respx, DynamoDB with moto. Everything between argv and
the wire is the production code path, which is what separates it from the smoke tier
(surface only, no provider reached) and the unit tier (pure functions, no I/O).

It replaces the standalone scripts this suite used to carry. Those were not collected
by pytest, so the checks that exercised pagination, rendering and failure paths never
ran in CI.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse retry backoff so a retry test costs no wall-clock time.

    The transport sleeps between attempts and honours `Retry-After`. Tests assert that
    a retry happened, not that it waited, so the delay is pure cost. Patches
    `asyncio.sleep` rather than the transport, so the retry logic under test is
    untouched.
    """
    import asyncio

    real_sleep = asyncio.sleep

    async def instant(_delay: float, *args: object, **kwargs: object) -> None:
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.fixture
def seen() -> list[str]:
    """Collector for request URLs, so a test can assert on what reached the provider.

    Kept as a plain list rather than reading respx's call log, because the assertions
    are about the query string a command built, and the raw URL is the clearest form of
    that.
    """
    return []
