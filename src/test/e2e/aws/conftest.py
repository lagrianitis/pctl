"""Fixtures for the DynamoDB end-to-end tests.

AWS is faked at the wire with moto, driving real boto3 clients against it, so these
tests exercise the same serialisation, pagination and error shapes as production. A
`MagicMock` client would accept any call and keep passing through an API change, which
is the opposite of what this tier is for.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from helpers import ITEM_COUNT, REGION, TABLE


@pytest.fixture(autouse=True)
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dummy credentials and a fixed region, so a real profile can never be reached.

    Autouse and unconditional: without it, boto3 would fall through to the developer's
    profile, SSO session or instance credentials, and a test could hit a live account.
    `AWS_PROFILE` is cleared for the same reason, and the config files are pointed at
    /dev/null so a shared `~/.aws/config` cannot supply one either.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/dev/null")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("PCTL_DYNAMODB_ENDPOINT_URL", raising=False)


@pytest.fixture
def ddb_table(aws_env: None) -> Iterator[str]:
    """A moto-backed table seeded with ITEM_COUNT items, yielding its name.

    Items carry a Decimal, a list and a map on purpose: those are the DynamoDB types
    whose deserialisation into plain JSON is easy to get wrong, and `budget` is
    fractional so a float round trip is visible.

    Per-test scoped. pytest-xdist runs across processes in an unspecified order, and a
    shared table would make the parallel-scan count assertions order-dependent.
    """
    import boto3
    from moto import mock_aws

    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
        for index in range(ITEM_COUNT):
            table.put_item(
                Item={
                    "pk": f"acct#{index:03d}",
                    "sk": "profile",
                    "status": "ACTIVE" if index % 2 else "SUSPENDED",
                    "budget": Decimal("1234.50"),
                    "count": Decimal("7"),
                    "tags": ["platform", "e2e"],
                    "meta": {"region": REGION},
                }
            )
        yield TABLE


@pytest.fixture
def empty_table(aws_env: None) -> Iterator[str]:
    """A moto-backed table with no items, for the empty-result paths."""
    import boto3
    from moto import mock_aws

    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield TABLE


@pytest.fixture
def ddb(runner: Any, cli: Any) -> Any:
    """Invoke `pctl aws ddb ...`, saving the case and service on every call.

    Pass the output format as `output=`, not as a positional `-o`. Global options are
    declared on the root group and on leaf commands, but not on the intermediate `ddb`
    group, so `pctl aws ddb -o ndjson tables` is a usage error while
    `pctl -o ndjson aws ddb tables` is not. This keyword puts it in the root position.
    """

    def invoke(*args: str, output: str | None = None) -> Any:
        root = ["-o", output] if output else []
        return runner.invoke(cli, [*root, "aws", "ddb", *args], prog_name="pctl")

    return invoke
