"""Unit tier: the request-state classifier behind `--wait`.

Whether a write is reported as applied comes down to this one function. Getting it wrong
means either claiming success for access that never arrived, or failing a pipeline that
actually worked. No I/O, so it is pinned here rather than through a faked provider.
"""

from __future__ import annotations

import pytest

from pctl.azure.entitlements.common import request_outcome

pytestmark = pytest.mark.unit


def test_delivered_is_the_only_done_state() -> None:
    assert request_outcome("delivered") == "done"


def test_state_comparison_folds_case() -> None:
    """v1.0 documents lower-camel, but tenants have been seen returning capitalised."""
    assert request_outcome("Delivered") == "done"
    assert request_outcome("DELIVERED") == "done"


def test_surrounding_whitespace_is_tolerated() -> None:
    assert request_outcome("  delivered  ") == "done"


@pytest.mark.parametrize("state", ["denied", "canceled", "cancelled", "deliveryFailed", "failed"])
def test_terminal_failures_are_classified_as_failed(state: str) -> None:
    assert request_outcome(state) == "failed"


def test_partial_delivery_is_its_own_outcome() -> None:
    """Microsoft's guidance is to reprocess these, so they are not plain failures."""
    assert request_outcome("partiallyDelivered") == "partial"


@pytest.mark.parametrize(
    "state",
    ["submitted", "pendingApproval", "accepted", "delivering", "scheduled", "pendingNotBefore"],
)
def test_in_flight_states_are_pending(state: str) -> None:
    assert request_outcome(state) == "pending"


def test_an_unrecognised_state_is_pending_not_done() -> None:
    """The safe default. Never report access that may not exist."""
    assert request_outcome("somethingBrandNew") == "pending"


def test_a_missing_state_is_pending() -> None:
    assert request_outcome(None) == "pending"
    assert request_outcome("") == "pending"
