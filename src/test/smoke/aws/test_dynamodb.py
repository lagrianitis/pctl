"""Smoke tier: the `pctl aws ddb` surface.

Help text and argument validation only. Every case here fails or returns during click
parsing, so no AWS call is ever attempted - which the tier's autouse fixture also
enforces by stripping credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke

TABLE = "some-table"


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------
def test_the_service_help_lists_its_actions(ddb: Callable[..., Any]) -> None:
    stdout = ok(ddb("--help")).stdout
    for action in ("tables", "describe", "scan", "query", "get"):
        assert action in stdout


def test_scan_help_keeps_its_examples(ddb: Callable[..., Any]) -> None:
    """Command docstrings are user-facing help; the examples must survive."""
    stdout = ok(ddb("scan", "--help")).stdout
    assert "pctl aws ddb scan" in stdout


def test_scan_help_documents_parallel_segments(ddb: Callable[..., Any]) -> None:
    assert "--segments" in ok(ddb("scan", "--help")).stdout


def test_query_help_documents_the_key_condition(ddb: Callable[..., Any]) -> None:
    assert "KeyConditionExpression" in ok(ddb("query", "--help")).stdout


# ---------------------------------------------------------------------------
# required arguments
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "args",
    [
        ("describe",),
        ("scan",),
        ("query",),
        ("get",),
        ("get", TABLE),
    ],
    ids=["describe", "scan", "query", "get-no-args", "get-table-only"],
)
def test_missing_required_arguments_are_usage_errors(
    ddb: Callable[..., Any], args: tuple[str, ...]
) -> None:
    failed(ddb(*args), 2)


def test_query_without_a_key_condition_is_a_usage_error(ddb: Callable[..., Any]) -> None:
    result = failed(ddb("query", TABLE), 2)
    assert "--key" in result.output


# ---------------------------------------------------------------------------
# option validation
# ---------------------------------------------------------------------------
def test_a_malformed_json_key_is_rejected(ddb: Callable[..., Any]) -> None:
    """Parsed before any AWS call, so this needs no fake service."""
    result = failed(ddb("get", TABLE, "{not json"), 2)
    assert "invalid JSON" in result.output


def test_a_non_object_json_key_is_rejected(ddb: Callable[..., Any]) -> None:
    failed(ddb("get", TABLE, '["a"]'), 2)


def test_too_many_segments_are_rejected(ddb: Callable[..., Any]) -> None:
    failed(ddb("scan", TABLE, "--segments", "999"), 2)


def test_a_zero_limit_is_rejected(ddb: Callable[..., Any]) -> None:
    failed(ddb("scan", TABLE, "-n", "0"), 2)


def test_an_out_of_range_page_size_is_rejected(ddb: Callable[..., Any]) -> None:
    failed(ddb("scan", TABLE, "--page-size", "5000"), 2)


def test_an_unknown_action_is_a_usage_error(ddb: Callable[..., Any]) -> None:
    failed(ddb("nope"), 2)


# ---------------------------------------------------------------------------
# aliases and prefixes
# ---------------------------------------------------------------------------
def test_the_dynamodb_alias_reaches_the_same_group(runner: Any, cli: Any) -> None:
    result = ok(runner.invoke(cli, ["aws", "dynamodb", "--help"], prog_name="pctl"))
    assert "DynamoDB" in result.stdout


def test_an_unambiguous_action_prefix_resolves(ddb: Callable[..., Any]) -> None:
    """`sc` can only be `scan`. click echoes the path as typed, so identify the
    command by its options rather than by the usage line."""
    assert "--segments" in ok(ddb("sc", "--help")).stdout
