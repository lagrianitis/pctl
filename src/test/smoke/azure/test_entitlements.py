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
    for action in (
        "list-packages",
        "get-package",
        "delete-package",
        "list-catalogs",
        "get-catalog",
        "list-assignments",
    ):
        assert action in stdout


def test_assignments_help_documents_the_package_scope(eam: Callable[..., Any]) -> None:
    stdout = ok(eam("list-assignments", "--help")).stdout
    assert "--access-package" in stdout
    assert "--state" in stdout


def test_assignments_help_lists_the_graph_states(eam: Callable[..., Any]) -> None:
    """Capitalised exactly as Graph expects, since the filter is case-sensitive."""
    stdout = ok(eam("list-assignments", "--help")).stdout
    for state in ("Delivered", "Expired", "DeliveryFailed"):
        assert state in stdout


def test_a_lowercase_state_is_rejected(eam: Callable[..., Any]) -> None:
    failed(eam("list-assignments", "--state", "delivered"), 2)


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
    failed(eam("get-package", "--access-package", "x", "--match", "search"), 2)


def test_get_package_without_an_identifier_is_a_usage_error(eam: Callable[..., Any]) -> None:
    failed(eam("get-package"), 2)


def test_get_catalog_without_an_identifier_is_a_usage_error(eam: Callable[..., Any]) -> None:
    failed(eam("get-catalog"), 2)


def test_an_invalid_page_size_is_rejected(eam: Callable[..., Any]) -> None:
    failed(eam("list-packages", "--page-size", "0"), 2)


# ---------------------------------------------------------------------------
# the two assignment writes
# ---------------------------------------------------------------------------
def test_add_assignment_help_names_the_write_permission(eam: Callable[..., Any]) -> None:
    assert "ReadWrite" in ok(eam("add-assignment", "--help")).stdout


def test_remove_assignment_help_names_the_write_permission(eam: Callable[..., Any]) -> None:
    assert "ReadWrite" in ok(eam("remove-assignment", "--help")).stdout


def test_add_assignment_help_documents_idempotency(eam: Callable[..., Any]) -> None:
    assert "Idempotent" in ok(eam("add-assignment", "--help")).stdout


def test_add_assignment_help_warns_the_request_is_asynchronous(
    eam: Callable[..., Any],
) -> None:
    """Access does not exist the moment the command exits, which surprises people."""
    assert "asynchronously" in ok(eam("add-assignment", "--help")).stdout


def test_remove_assignment_help_warns_the_request_is_asynchronous(
    eam: Callable[..., Any],
) -> None:
    assert "asynchronously" in ok(eam("remove-assignment", "--help")).stdout


def test_add_assignment_offers_a_policy_option(eam: Callable[..., Any]) -> None:
    assert "--policy" in ok(eam("add-assignment", "--help")).stdout


def test_remove_assignment_has_no_policy_option(eam: Callable[..., Any]) -> None:
    """adminRemove names the assignment, so a policy would be meaningless."""
    assert "--policy" not in ok(eam("remove-assignment", "--help")).stdout


def test_both_writes_accept_comma_separated_emails(eam: Callable[..., Any]) -> None:
    for action in ("add-assignment", "remove-assignment"):
        assert "--emails" in ok(eam(action, "--help")).stdout


def test_add_assignment_needs_a_package(eam: Callable[..., Any]) -> None:
    failed(eam("add-assignment"), 2)


def test_add_assignment_needs_at_least_one_person(eam: Callable[..., Any]) -> None:
    failed(eam("add-assignment", "--access-package", "some-package"), 2)


def test_add_assignment_needs_the_package_flag(eam: Callable[..., Any]) -> None:
    """The package is a named flag, so it cannot be confused with a target."""
    failed(eam("add-assignment", "--target", "ann@example.com"), 2)


def test_remove_assignment_needs_at_least_one_person(eam: Callable[..., Any]) -> None:
    failed(eam("remove-assignment", "--access-package", "some-package"), 2)


def test_remove_assignment_needs_the_package_flag(eam: Callable[..., Any]) -> None:
    failed(eam("remove-assignment", "--target", "ann@example.com"), 2)


def test_both_writes_offer_wait(eam: Callable[..., Any]) -> None:
    """The only way to know a write applied, so it belongs in both help screens."""
    for action in ("add-assignment", "remove-assignment"):
        stdout = ok(eam(action, "--help")).stdout
        assert "--wait" in stdout
        assert "--wait-timeout" in stdout


def test_get_request_is_listed(eam: Callable[..., Any]) -> None:
    assert "get-request" in ok(eam("--help")).stdout


def test_get_request_help_explains_the_outcome_classification(eam: Callable[..., Any]) -> None:
    stdout = ok(eam("get-request", "--help")).stdout
    for word in ("delivered", "pending", "outcome"):
        assert word in stdout


def test_get_request_needs_an_id(eam: Callable[..., Any]) -> None:
    failed(eam("get-request"), 2)


def test_a_zero_wait_timeout_is_rejected(eam: Callable[..., Any]) -> None:
    failed(
        eam("add-assignment", "--access-package", "p", "a@b.com", "--wait-timeout", "0"),
        2,
    )


# ---------------------------------------------------------------------------
# delete-package
# ---------------------------------------------------------------------------
def test_delete_package_help_says_it_cannot_be_undone(eam: Callable[..., Any]) -> None:
    """The only destructive command, so the help must lead with that."""
    assert "cannot be undone" in ok(eam("delete-package", "--help")).stdout


def test_delete_package_help_names_the_write_permission(eam: Callable[..., Any]) -> None:
    assert "EntitlementManagement.ReadWrite.All" in ok(eam("delete-package", "--help")).stdout


def test_delete_package_help_documents_the_confirmation(eam: Callable[..., Any]) -> None:
    stdout = ok(eam("delete-package", "--help")).stdout
    assert "--yes" in stdout
    assert "--force" in stdout


def test_delete_package_rejects_a_match_option(eam: Callable[..., Any]) -> None:
    """A pattern must not be able to choose what gets deleted.

    Asserted by rejecting the option rather than by checking it is absent from the help
    text, which it is not: the docstring explains at length that there is deliberately no
    --match here, so the string appears in the prose.
    """
    failed(eam("delete-package", "--access-package", "a", "--match", "contains"), 2)


def test_delete_package_needs_the_package_flag(eam: Callable[..., Any]) -> None:
    result = failed(eam("delete-package"), 2)
    assert "--access-package" in result.output
