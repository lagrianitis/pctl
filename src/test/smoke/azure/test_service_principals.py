"""Smoke tier: the `pctl azure sp` surface.

Help text and argument validation only. Nothing here acquires a token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


@pytest.fixture
def sp(azure: Callable[..., Any]) -> Callable[..., Any]:
    """Invoke `pctl azure sp ...`."""

    def invoke(*args: str) -> Any:
        return azure("sp", *args)

    return invoke


def test_the_service_help_lists_its_actions(sp: Callable[..., Any]) -> None:
    stdout = ok(sp("--help")).stdout
    for action in ("list", "get", "assignments"):
        assert action in stdout


def test_the_help_explains_the_portal_name(sp: Callable[..., Any]) -> None:
    """Nobody searches for "service principal" when the portal said Enterprise App."""
    assert "Enterprise Application" in ok(sp("--help")).stdout


def test_the_portal_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "assignments" in ok(azure("enterprise-apps", "--help")).stdout


def test_the_graph_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "assignments" in ok(azure("service-principals", "--help")).stdout


def test_the_case_help_lists_the_service(azure: Callable[..., Any]) -> None:
    assert "sp" in ok(azure("--help")).stdout


def test_get_help_documents_the_match_modes(sp: Callable[..., Any]) -> None:
    stdout = ok(sp("get", "--help")).stdout
    for mode in ("exact", "prefix", "search"):
        assert mode in stdout


def test_get_defaults_to_search_because_app_names_are_long(sp: Callable[..., Any]) -> None:
    """Unlike groups, which default to exact."""
    assert "search" in ok(sp("get", "--help")).stdout


def test_assignments_help_documents_both_directions(sp: Callable[..., Any]) -> None:
    stdout = ok(sp("assignments", "--help")).stdout
    assert "--outbound" in stdout
    assert "--principal" in stdout


def test_assignments_help_documents_the_principal_match_modes(sp: Callable[..., Any]) -> None:
    stdout = ok(sp("assignments", "--help")).stdout
    for mode in ("exact", "prefix", "contains"):
        assert mode in stdout


def test_an_unknown_principal_match_mode_is_rejected(sp: Callable[..., Any]) -> None:
    """Rejected at parse time, so a typo cannot silently widen an access check."""
    failed(sp("assignments", "app", "--principal", "x", "--principal-match", "search"), 2)


def test_list_help_documents_app_id_lookup(sp: Callable[..., Any]) -> None:
    assert "--app-id" in ok(sp("list", "--help")).stdout


def test_get_without_a_name_is_a_usage_error(sp: Callable[..., Any]) -> None:
    failed(sp("get"), 2)


def test_assignments_without_a_name_is_a_usage_error(sp: Callable[..., Any]) -> None:
    failed(sp("assignments"), 2)


def test_an_unknown_match_mode_is_rejected(sp: Callable[..., Any]) -> None:
    failed(sp("get", "whatever", "--match", "fuzzy"), 2)
