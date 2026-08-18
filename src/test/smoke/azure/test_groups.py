"""Smoke tier: the `pctl azure groups` surface.

Help text and argument validation only. Nothing here acquires a token, so the tests
stay fast and need no tenant.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------
def test_the_service_help_lists_its_actions(groups: Callable[..., Any]) -> None:
    stdout = ok(groups("--help")).stdout
    for action in ("list", "get", "members"):
        assert action in stdout


def test_list_help_keeps_its_examples(groups: Callable[..., Any]) -> None:
    assert "pctl azure groups list" in ok(groups("list", "--help")).stdout


def test_get_help_documents_the_match_modes(groups: Callable[..., Any]) -> None:
    """`--match` is the difference between finding a group and not finding it."""
    stdout = ok(groups("get", "--help")).stdout
    for mode in ("exact", "prefix", "search"):
        assert mode in stdout


def test_get_help_documents_reading_names_from_a_file(groups: Callable[..., Any]) -> None:
    assert "--from-file" in ok(groups("get", "--help")).stdout


def test_credentials_are_documented_on_the_case(azure: Callable[..., Any]) -> None:
    """Where credentials come from is the first thing a new user needs."""
    stdout = ok(azure("--help")).stdout
    assert "AZURE_CLIENT_SECRET" in stdout
    assert "--secret-id" in stdout


def test_no_option_offers_to_take_a_secret_value(groups: Callable[..., Any]) -> None:
    """A secret must never be a flag, since flags land in shell history and `ps`."""
    for action in ("list", "get", "members"):
        stdout = ok(groups(action, "--help")).stdout
        assert "--client-secret" not in stdout


# ---------------------------------------------------------------------------
# required arguments and option validation
# ---------------------------------------------------------------------------
def test_get_without_names_explains_the_alternatives(groups: Callable[..., Any]) -> None:
    result = failed(groups("get"), 2)
    assert "--from-file" in result.output


def test_members_requires_a_group_name(groups: Callable[..., Any]) -> None:
    failed(groups("members"), 2)


def test_an_unknown_match_mode_is_rejected(groups: Callable[..., Any]) -> None:
    failed(groups("get", "Team A", "--match", "fuzzy"), 2)


def test_a_zero_limit_is_rejected(groups: Callable[..., Any]) -> None:
    failed(groups("list", "-n", "0"), 2)


def test_an_out_of_range_page_size_is_rejected(groups: Callable[..., Any]) -> None:
    failed(groups("list", "--page-size", "1000"), 2)


def test_an_unknown_action_is_a_usage_error(groups: Callable[..., Any]) -> None:
    failed(groups("nope"), 2)


# ---------------------------------------------------------------------------
# aliases and prefixes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("args", [["az"], ["graph"]], ids=["az", "graph"])
def test_the_case_aliases_resolve(runner: Any, cli: Any, args: list[str]) -> None:
    result = ok(runner.invoke(cli, [*args, "--help"], prog_name="pctl"))
    assert "Microsoft Graph" in result.stdout


def test_nested_prefixes_resolve(runner: Any, cli: Any) -> None:
    """`pctl az gr li` is the shortest way to reach groups list.

    click echoes the path as typed, so the command is identified by its help body
    rather than by the usage line.
    """
    result = ok(runner.invoke(cli, ["az", "gr", "li", "--help"], prog_name="pctl"))
    assert "List every group in the tenant" in result.stdout
