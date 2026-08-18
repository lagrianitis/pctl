"""End-to-end: how `pctl aws ddb` fails.

Exit codes are a published contract, so they are asserted against the real command
path. botocore raises the same error shapes through moto as it does in production,
which is why these tests can trust the mapping.
"""

from __future__ import annotations

from typing import Any

import pytest

from helpers import failed

pytestmark = pytest.mark.e2e


def test_a_missing_item_exits_4(ddb: Any, ddb_table: str) -> None:
    """DynamoDB returns an empty response rather than an error, so the CLI decides."""
    failed(ddb("get", ddb_table, '{"pk":"missing","sk":"profile"}'), 4)


def test_an_unknown_table_exits_4_and_names_it(ddb: Any, ddb_table: str) -> None:
    result = failed(ddb("scan", "no-such-table"), 4)

    assert "no-such-table" in result.output


def test_a_malformed_json_key_is_a_usage_error(ddb: Any, ddb_table: str) -> None:
    """Exit 2, not 5: the input never left the process, so it is not upstream's fault."""
    failed(ddb("get", ddb_table, "{not json"), 2)


def test_a_key_condition_without_values_is_reported_as_upstream(ddb: Any, ddb_table: str) -> None:
    """`--key` names :pk but nothing binds it, and DynamoDB is what rejects that.

    Exit 5 rather than 2 because the validation happens server-side. Worth asserting so
    the code does not quietly change when someone adds client-side checking.
    """
    failed(ddb("query", ddb_table, "--key", "pk = :pk"), 5)
