"""Smoke tier: the `pctl azure eam` surface.

Help text and argument validation only. Nothing here acquires a token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


@pytest.fixture
def eam(azure: Callable[..., Any]) -> Callable[..., Any]:
    """Invoke `pctl azure eam ...`."""

    def invoke(*args: str) -> Any:
        return azure("eam", *args)

    return invoke


def test_the_service_help_lists_its_actions(eam: Callable[..., Any]) -> None:
    stdout = ok(eam("--help")).stdout
    for action in ("list-packages", "get-package", "list-catalogs", "get-catalog"):
        assert action in stdout


def test_the_case_help_lists_the_service(azure: Callable[..., Any]) -> None:
    assert "eam" in ok(azure("--help")).stdout


def test_the_long_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "list-packages" in ok(azure("entitlement-management", "--help")).stdout


def test_the_access_packages_alias_resolves(azure: Callable[..., Any]) -> None:
    assert "list-packages" in ok(azure("access-packages", "--help")).stdout


def test_list_help_says_contains_is_local(eam: Callable[..., Any]) -> None:
    """The one surprise in this service, so it belongs in the help rather than a docs page."""
    assert "locally" in ok(eam("list-packages", "--help")).stdout


def test_list_packages_offers_a_catalog_scope(eam: Callable[..., Any]) -> None:
    """Scoping by catalog name is the common way to make the result readable."""
    assert "--catalog" in ok(eam("list-packages", "--help")).stdout


def test_catalogs_have_no_catalog_scope_of_their_own(eam: Callable[..., Any]) -> None:
    """Catalogs do not nest, so the option would be meaningless there."""
    assert "--catalog " not in ok(eam("list-catalogs", "--help")).stdout


def test_list_help_does_not_offer_search(eam: Callable[..., Any]) -> None:
    """$search is unsupported here, so offering it would be a promise Graph breaks."""
    assert "--search" not in ok(eam("list-packages", "--help")).stdout


def test_get_package_documents_the_match_modes(eam: Callable[..., Any]) -> None:
    stdout = ok(eam("get-package", "--help")).stdout
    for mode in ("exact", "prefix", "contains"):
        assert mode in stdout


def test_get_package_offers_the_policy_expansion(eam: Callable[..., Any]) -> None:
    assert "--with-policies" in ok(eam("get-package", "--help")).stdout


def test_search_is_not_a_valid_match_mode(eam: Callable[..., Any]) -> None:
    failed(eam("get-package", "anything", "--match", "search"), 2)


def test_get_package_without_an_identifier_is_a_usage_error(eam: Callable[..., Any]) -> None:
    failed(eam("get-package"), 2)


def test_get_catalog_without_an_identifier_is_a_usage_error(eam: Callable[..., Any]) -> None:
    failed(eam("get-catalog"), 2)


def test_an_invalid_page_size_is_rejected(eam: Callable[..., Any]) -> None:
    failed(eam("list-packages", "--page-size", "0"), 2)
