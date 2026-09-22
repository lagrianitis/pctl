"""Unit tier: the pure helpers behind `pctl azure sp`.

No I/O. Filtering and role labelling are plain functions on already-fetched data, so
they are cheaper to pin down here than through a faked provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from pctl.azure.service_principals.common import filter_by_principal, label_roles

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


def test_a_partial_name_does_not_match() -> None:
    """Deliberately exact: a substring match would silently widen an access check."""
    assert filter_by_principal([_assignment("AWS Platform Admins")], "Platform") == []


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
