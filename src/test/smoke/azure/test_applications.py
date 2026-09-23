"""Smoke tier: the `pctl azure apps` surface.

Help text and argument validation only. Nothing here acquires a token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


@pytest.fixture
def apps(azure: Callable[..., Any]) -> Callable[..., Any]:
    """Invoke `pctl azure apps ...`."""

    def invoke(*args: str) -> Any:
        return azure("apps", *args)

    return invoke


def test_the_service_help_lists_its_actions(apps: Callable[..., Any]) -> None:
    stdout = ok(apps("--help")).stdout
    assert "list" in stdout
    assert "get" in stdout


def test_the_case_help_lists_the_service(azure: Callable[..., Any]) -> None:
    assert "apps" in ok(azure("--help")).stdout


def test_the_portal_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "get" in ok(azure("app-registrations", "--help")).stdout


def test_the_graph_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "get" in ok(azure("applications", "--help")).stdout


def test_the_help_distinguishes_apps_from_service_principals(apps: Callable[..., Any]) -> None:
    """These two are the easiest pair in the tool to confuse, so say which is which."""
    assert "service principal" in ok(apps("--help")).stdout.lower()


def test_get_help_explains_the_two_guids(apps: Callable[..., Any]) -> None:
    stdout = ok(apps("get", "--help")).stdout
    assert "appId" in stdout
    assert "object ID" in stdout


def test_get_help_documents_the_service_principal_join(apps: Callable[..., Any]) -> None:
    assert "--with-sp" in ok(apps("get", "--help")).stdout


def test_list_help_keeps_its_examples(apps: Callable[..., Any]) -> None:
    assert "pctl azure apps list" in ok(apps("list", "--help")).stdout


def test_get_without_an_identifier_is_a_usage_error(apps: Callable[..., Any]) -> None:
    failed(apps("get"), 2)


def test_an_unknown_match_mode_is_rejected(apps: Callable[..., Any]) -> None:
    failed(apps("get", "--app", "whatever", "--match", "fuzzy"), 2)


def test_an_invalid_page_size_is_rejected(apps: Callable[..., Any]) -> None:
    failed(apps("list", "--page-size", "0"), 2)
