"""Fixtures shared by every end-to-end test.

This tier drives the real CLI through `CliRunner` and fakes only the provider
boundary: Microsoft Graph with respx, DynamoDB and Secrets Manager with moto. Everything
between argv and the wire is the production code path, which is what separates it from the
smoke tier (surface only, no provider reached) and the unit tier (pure functions, no I/O).

It replaces the standalone scripts this suite used to carry. Those were not collected
by pytest, so the checks that exercised pagination, rendering and failure paths never
ran in CI.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from helpers import REGION


class SecretStore:
    """A moto-backed Secrets Manager, with helpers to seed a secret and read one back."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def create(self, name: str, value: dict[str, Any] | str) -> None:
        text = value if isinstance(value, str) else json.dumps(value)
        self.client.create_secret(Name=name, SecretString=text)

    def read(self, name: str) -> dict[str, Any]:
        return dict(json.loads(self.client.get_secret_value(SecretId=name)["SecretString"]))


@pytest.fixture
def secrets_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[SecretStore]:
    """Secrets Manager faked at the wire, with credentials that can reach nothing real.

    Shared by the Azure and AWS cases, because storing a new client secret crosses both.
    It sets its own dummy credentials and region rather than leaning on the AWS case's
    autouse fixture, so a test under `azure/` is isolated from a developer's profile too.
    Per-test scoped: a shared store would make the order tests run in matter.
    """
    import boto3
    from moto import mock_aws

    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        yield SecretStore(boto3.client("secretsmanager", region_name=REGION))


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
