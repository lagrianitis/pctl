"""Smoke tier: the `pctl azure users` surface.

Help text and argument validation only. Nothing here acquires a token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


@pytest.fixture
def users(azure: Callable[..., Any]) -> Callable[..., Any]:
    """Invoke `pctl azure users ...`."""

    def invoke(*args: str) -> Any:
        return azure("users", *args)

    return invoke


def test_the_service_help_lists_its_actions(users: Callable[..., Any]) -> None:
    assert "get" in ok(users("--help")).stdout


def test_the_case_help_lists_the_service(azure: Callable[..., Any]) -> None:
    assert "users" in ok(azure("--help")).stdout


def test_get_help_documents_all_three_identifier_forms(users: Callable[..., Any]) -> None:
    """The whole point is that you pass whatever you happen to know."""
    stdout = ok(users("get", "--help")).stdout
    for form in ("email", "display name", "object ID"):
        assert form in stdout


def test_get_help_documents_the_match_modes(users: Callable[..., Any]) -> None:
    stdout = ok(users("get", "--help")).stdout
    for mode in ("exact", "prefix", "search"):
        assert mode in stdout


def test_get_help_documents_reading_from_a_file(users: Callable[..., Any]) -> None:
    assert "--from-file" in ok(users("get", "--help")).stdout


def test_get_without_an_identifier_is_a_usage_error(users: Callable[..., Any]) -> None:
    failed(users("get"), 2)


def test_an_unknown_match_mode_is_rejected(users: Callable[..., Any]) -> None:
    failed(users("get", "--user", "ann@example.com", "--match", "fuzzy"), 2)


def test_the_service_resolves_by_prefix(azure: Callable[..., Any]) -> None:
    """`pctl azure us get` should work, since prefixes are unambiguous here."""
    assert "get" in ok(azure("us", "--help")).stdout
