"""Unit tier: the case-level directory helpers in `azure/common.py`.

These decide which of three forms an argument is — object ID, email address, display
name — without a flag to declare it. Both `users get` and the `sp` owner arguments depend
on that guess being right, so the edges are pinned here rather than through a provider.
"""

from __future__ import annotations

import pytest

from pctl.azure.common import looks_like_email, looks_like_object_id

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# looks_like_object_id
# ---------------------------------------------------------------------------
def test_a_canonical_guid_is_recognised() -> None:
    assert looks_like_object_id("e6901838-637f-4bc7-b843-a8a7725a4872")


def test_an_uppercase_guid_is_recognised() -> None:
    """Portal copy-paste is often uppercase."""
    assert looks_like_object_id("E6901838-637F-4BC7-B843-A8A7725A4872")


def test_surrounding_whitespace_is_tolerated() -> None:
    assert looks_like_object_id("  e6901838-637f-4bc7-b843-a8a7725a4872  ")


def test_a_display_name_is_not_an_object_id() -> None:
    assert not looks_like_object_id("Ann Example")


def test_a_name_that_merely_contains_a_guid_is_not_one() -> None:
    """fullmatch, not search: such a name must still be resolved as a name."""
    assert not looks_like_object_id("app e6901838-637f-4bc7-b843-a8a7725a4872 prod")


def test_a_truncated_guid_is_not_an_object_id() -> None:
    assert not looks_like_object_id("e6901838-637f-4bc7-b843")


def test_an_empty_string_is_not_an_object_id() -> None:
    assert not looks_like_object_id("")


# ---------------------------------------------------------------------------
# looks_like_email
# ---------------------------------------------------------------------------
def test_an_address_is_recognised() -> None:
    assert looks_like_email("lef@company.com")


def test_an_onmicrosoft_upn_is_recognised() -> None:
    """UPN and mail routinely differ, and either may be what the caller knows."""
    assert looks_like_email("lef@company.onmicrosoft.com")


def test_a_display_name_is_not_an_address() -> None:
    assert not looks_like_email("Lefteris Agrianitis")


def test_an_object_id_is_not_an_address() -> None:
    assert not looks_like_email("e6901838-637f-4bc7-b843-a8a7725a4872")


def test_surrounding_whitespace_does_not_hide_an_address() -> None:
    assert looks_like_email("  lef@company.com  ")


def test_the_three_forms_are_mutually_exclusive() -> None:
    """A value must not be read as two different kinds of identifier."""
    guid = "e6901838-637f-4bc7-b843-a8a7725a4872"
    address = "ann@example.com"
    name = "Ann Example"

    assert looks_like_object_id(guid) and not looks_like_email(guid)
    assert looks_like_email(address) and not looks_like_object_id(address)
    assert not looks_like_object_id(name) and not looks_like_email(name)
