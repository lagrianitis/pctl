"""Unit tier: the pure helpers behind `pctl azure sp`.

No I/O. Filtering and role labelling are plain functions on already-fetched data, so
they are cheaper to pin down here than through a faked provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from pctl.azure.service_principals.common import (
    filter_by_principal,
    label_roles,
    owner_label,
)

pytestmark = pytest.mark.unit

ROLE_ID = "11111111-2222-3333-4444-555555555555"


def _assignment(principal: str | None, role: str | None = ROLE_ID) -> dict[str, Any]:
    return {"principalDisplayName": principal, "appRoleId": role}


# ---------------------------------------------------------------------------
# filter_by_principal
# ---------------------------------------------------------------------------
def test_no_principal_returns_everything_unchanged() -> None:
    items = [_assignment("Ann"), _assignment("Bob")]

    assert filter_by_principal(items, None) == items


def test_an_exact_principal_name_matches() -> None:
    items = [_assignment("Ann"), _assignment("Bob")]

    assert filter_by_principal(items, "Ann") == [items[0]]


def test_matching_ignores_case() -> None:
    """Portal display names are typed by hand, so case is not a useful distinction."""
    items = [_assignment("AWS Platform Admins")]

    assert filter_by_principal(items, "aws platform admins") == items


def test_a_partial_name_does_not_match_by_default() -> None:
    """Exact is the default: a substring match would silently widen an access check."""
    assert filter_by_principal([_assignment("AWS Platform Admins")], "Platform") == []


# ---------------------------------------------------------------------------
# filter_by_principal: match modes
# ---------------------------------------------------------------------------
def test_prefix_mode_matches_the_start_of_the_name() -> None:
    items = [_assignment("aws-platform"), _assignment("aws-billing"), _assignment("gcp-platform")]

    matched = filter_by_principal(items, "aws-", mode="prefix")

    assert [item["principalDisplayName"] for item in matched] == ["aws-platform", "aws-billing"]


def test_prefix_mode_does_not_match_mid_string() -> None:
    assert (
        filter_by_principal([_assignment("AWS Platform Admins")], "Platform", mode="prefix") == []
    )


def test_contains_mode_matches_anywhere_in_the_name() -> None:
    items = [_assignment("AWS Platform Admins"), _assignment("GCP Platform"), _assignment("Other")]

    matched = filter_by_principal(items, "platform", mode="contains")

    assert len(matched) == 2


def test_prefix_mode_ignores_case() -> None:
    assert filter_by_principal([_assignment("AWS Platform")], "aws", mode="prefix") != []


def test_contains_mode_ignores_case() -> None:
    assert filter_by_principal([_assignment("AWS Platform")], "PLATFORM", mode="contains") != []


def test_an_unknown_mode_is_an_error_not_a_silent_pass() -> None:
    """A typo in the mode must not quietly return everything."""
    with pytest.raises(ValueError, match="unknown principal match mode"):
        filter_by_principal([_assignment("Ann")], "Ann", mode="fuzzy")


def test_no_principal_skips_matching_entirely_whatever_the_mode() -> None:
    items = [_assignment("Ann")]

    assert filter_by_principal(items, None, mode="fuzzy") == items


def test_a_missing_principal_display_name_is_skipped_not_crashed() -> None:
    """Graph omits the field on some assignment shapes."""
    items = [_assignment(None), _assignment("Ann")]

    assert filter_by_principal(items, "Ann") == [items[1]]


def test_no_match_yields_an_empty_list() -> None:
    assert filter_by_principal([_assignment("Ann")], "Bob") == []


# ---------------------------------------------------------------------------
# label_roles
# ---------------------------------------------------------------------------
def test_a_known_role_id_gains_its_display_name() -> None:
    items = [_assignment("Ann")]

    label_roles(items, {ROLE_ID: "User"})

    assert items[0]["appRoleName"] == "User"


def test_an_unknown_role_id_falls_back_to_the_guid() -> None:
    """Better an unreadable GUID than a missing column."""
    items = [_assignment("Ann")]

    label_roles(items, {})

    assert items[0]["appRoleName"] == ROLE_ID


def test_an_assignment_without_a_role_id_is_left_alone() -> None:
    items = [_assignment("Ann", role=None)]

    label_roles(items, {ROLE_ID: "User"})

    assert "appRoleName" not in items[0]


def test_labelling_mutates_in_place_and_returns_nothing() -> None:
    items = [_assignment("Ann")]

    assert label_roles(items, {ROLE_ID: "User"}) is None
    assert items[0]["appRoleName"] == "User"


# ---------------------------------------------------------------------------
# owner_label
# ---------------------------------------------------------------------------
def test_a_resolved_owner_is_labelled_with_name_and_id() -> None:
    owner = {"id": "u1", "displayName": "Ann Example", "_resolved": "users"}

    assert owner_label(owner) == "Ann Example (u1)"


def test_an_owner_given_as_an_id_says_so_rather_than_echoing_it_twice() -> None:
    owner = {"id": "u1", "displayName": "u1", "_resolved": "object-id"}

    assert owner_label(owner) == "object u1"


def test_the_upn_stands_in_when_there_is_no_display_name() -> None:
    owner = {"id": "u1", "userPrincipalName": "ann@example.com", "_resolved": "users"}

    assert owner_label(owner) == "ann@example.com (u1)"


def test_the_id_stands_in_when_there_is_no_name_at_all() -> None:
    assert owner_label({"id": "u1", "_resolved": "users"}) == "u1 (u1)"
