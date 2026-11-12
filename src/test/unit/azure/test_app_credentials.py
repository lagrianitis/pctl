"""Unit tests for turning an application's credentials into rows, and judging their expiry.

Three things matter here. The rows must never carry more than the fields chosen for them,
since a Graph response can include a secret value or key material and a row that copied
whatever arrived would print it. The dates must sort and parse the way Graph sends them,
including the seven fractional digits that `datetime` would refuse before 3.11. And the
status rule has to be exact at its boundaries, which is why the moment is a parameter and
every case here sits on one side of an edge or the other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pctl.azure.applications.common import (
    credential_rows,
    credential_status,
    days_remaining,
    parse_graph_time,
    with_expiry,
)

pytestmark = pytest.mark.unit

ROW_FIELDS = {"app", "appId", "type", "name", "keyId", "startDateTime", "endDateTime", "hint"}


def secret(name: str, end: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "displayName": name,
        "keyId": f"key-{name}",
        "startDateTime": "2026-01-01T00:00:00Z",
        "endDateTime": end,
        "hint": "abc",
        **extra,
    }


def registration(**collections: Any) -> dict[str, Any]:
    return {"id": "object-id", "appId": "client-id", "displayName": "ci-app", **collections}


# ---------------------------------------------------------------------------
# the rows
# ---------------------------------------------------------------------------
def test_each_secret_and_certificate_is_a_row() -> None:
    rows = credential_rows(
        registration(
            passwordCredentials=[secret("deploy", "2027-01-01T00:00:00Z")],
            keyCredentials=[secret("signing", "2028-01-01T00:00:00Z")],
        )
    )

    assert [(row["type"], row["name"]) for row in rows] == [
        ("secret", "deploy"),
        ("certificate", "signing"),
    ]


def test_the_soonest_to_expire_comes_first() -> None:
    """The one that matters most is the one about to lapse, whichever kind it is."""
    rows = credential_rows(
        registration(
            passwordCredentials=[secret("late", "2029-01-01T00:00:00Z")],
            keyCredentials=[secret("early", "2026-12-01T00:00:00Z")],
        )
    )

    assert [row["name"] for row in rows] == ["early", "late"]


def test_a_credential_with_no_end_date_sorts_last() -> None:
    rows = credential_rows(
        registration(
            passwordCredentials=[
                secret("undated", None),
                secret("dated", "2027-01-01T00:00:00Z"),
            ]
        )
    )

    assert [row["name"] for row in rows] == ["dated", "undated"]


def test_a_row_names_the_app_it_belongs_to() -> None:
    row = credential_rows(registration(passwordCredentials=[secret("deploy", None)]))[0]

    assert (row["app"], row["appId"]) == ("ci-app", "client-id")


def test_a_row_carries_exactly_the_chosen_fields() -> None:
    row = credential_rows(registration(passwordCredentials=[secret("deploy", None)]))[0]

    assert set(row) == ROW_FIELDS


def test_a_secret_value_is_never_copied() -> None:
    """Graph returns this only when a secret is created, but a row must not depend on that."""
    leaked = secret("deploy", None, secretText="LEAKED-VALUE", customKeyIdentifier="LEAKED-ID")

    row = credential_rows(registration(passwordCredentials=[leaked]))[0]

    assert "LEAKED-VALUE" not in str(row)
    assert "LEAKED-ID" not in str(row)


def test_certificate_key_material_is_never_copied() -> None:
    certificate = secret(
        "signing", None, key="LEAKED-KEY", usage="Verify", type="AsymmetricX509Cert"
    )

    row = credential_rows(registration(keyCredentials=[certificate]))[0]

    assert "LEAKED-KEY" not in str(row)


def test_only_a_secret_has_a_hint() -> None:
    rows = credential_rows(
        registration(
            passwordCredentials=[secret("deploy", "2027-01-01T00:00:00Z")],
            keyCredentials=[secret("signing", "2028-01-01T00:00:00Z")],
        )
    )

    assert {row["type"]: row["hint"] for row in rows} == {"secret": "abc", "certificate": None}


def test_no_credentials_is_an_empty_list() -> None:
    assert credential_rows(registration()) == []


def test_a_null_collection_is_tolerated() -> None:
    """Graph sends null for a collection it has nothing to put in."""
    assert credential_rows(registration(passwordCredentials=None, keyCredentials=None)) == []


def test_a_credential_missing_optional_fields_still_makes_a_row() -> None:
    row = credential_rows(registration(passwordCredentials=[{"keyId": "k"}]))[0]

    assert (row["name"], row["endDateTime"], row["hint"]) == (None, None, None)


# ---------------------------------------------------------------------------
# reading Graph's timestamps
# ---------------------------------------------------------------------------
def test_a_utc_timestamp_is_read() -> None:
    assert parse_graph_time("2027-04-20T10:15:00Z") == datetime(2027, 4, 20, 10, 15, tzinfo=UTC)


def test_seven_fractional_digits_are_read() -> None:
    """Graph and .NET write 100-nanosecond ticks, one digit more than microseconds."""
    assert parse_graph_time("2027-04-20T10:15:00.1234567Z") == datetime(
        2027, 4, 20, 10, 15, 0, 123456, tzinfo=UTC
    )


def test_an_offset_is_respected() -> None:
    parsed = parse_graph_time("2027-04-20T12:15:00+02:00")

    assert parsed == datetime(2027, 4, 20, 10, 15, tzinfo=UTC)
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=2)


def test_a_timestamp_with_no_zone_is_taken_as_utc() -> None:
    assert parse_graph_time("2027-04-20T10:15:00") == datetime(2027, 4, 20, 10, 15, tzinfo=UTC)


@pytest.mark.parametrize("value", [None, "", "not a date", "2027-13-45T99:99:99Z"])
def test_an_absent_or_unreadable_timestamp_is_none(value: str | None) -> None:
    assert parse_graph_time(value) is None


# ---------------------------------------------------------------------------
# status: where each boundary falls
# ---------------------------------------------------------------------------
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
WINDOW = timedelta(days=30)
SECOND = timedelta(seconds=1)


def status_at(offset: timedelta) -> str:
    """The status of a credential ending `offset` from NOW, under a 30 day window."""
    return credential_status(NOW + offset, NOW, WINDOW)


def test_a_credential_that_ended_in_the_past_is_expired() -> None:
    assert status_at(-SECOND) == "expired"


def test_a_credential_ending_this_very_instant_is_expired() -> None:
    """The deadline is not inclusive: at the end date it no longer works."""
    assert status_at(timedelta(0)) == "expired"


def test_a_credential_a_second_from_ending_is_expiring() -> None:
    assert status_at(SECOND) == "expiring"


def test_a_credential_a_second_inside_the_window_is_expiring() -> None:
    assert status_at(WINDOW - SECOND) == "expiring"


def test_a_credential_exactly_at_the_window_is_expiring() -> None:
    """The window is inclusive: thirty days away is still within thirty days."""
    assert status_at(WINDOW) == "expiring"


def test_a_credential_a_second_beyond_the_window_is_valid() -> None:
    assert status_at(WINDOW + SECOND) == "valid"


def test_a_credential_far_in_the_future_is_valid() -> None:
    assert status_at(timedelta(days=900)) == "valid"


def test_a_credential_with_no_end_date_is_unknown() -> None:
    assert credential_status(None, NOW, WINDOW) == "unknown"


def test_a_wider_window_catches_more() -> None:
    end = NOW + timedelta(days=45)

    assert credential_status(end, NOW, timedelta(days=30)) == "valid"
    assert credential_status(end, NOW, timedelta(days=60)) == "expiring"


# ---------------------------------------------------------------------------
# days remaining
# ---------------------------------------------------------------------------
def test_whole_days_are_counted() -> None:
    assert days_remaining(NOW + timedelta(days=10, hours=1), NOW) == 10


def test_days_are_rounded_down() -> None:
    """Nine days and 23 hours is nine days: it must never look longer than it is."""
    assert days_remaining(NOW + timedelta(days=10) - timedelta(hours=1), NOW) == 9


def test_less_than_a_day_left_is_zero() -> None:
    assert days_remaining(NOW + timedelta(hours=12), NOW) == 0


def test_ending_this_instant_is_zero() -> None:
    assert days_remaining(NOW, NOW) == 0


def test_a_lapsed_credential_is_negative() -> None:
    assert days_remaining(NOW - timedelta(hours=12), NOW) == -1
    assert days_remaining(NOW - timedelta(days=42), NOW) == -42


def test_no_end_date_has_no_days() -> None:
    assert days_remaining(None, NOW) is None


# ---------------------------------------------------------------------------
# adding the expiry to rows
# ---------------------------------------------------------------------------
def test_expiry_adds_the_days_and_the_status() -> None:
    rows = credential_rows(
        registration(passwordCredentials=[secret("deploy", "2026-11-22T12:00:00Z")])
    )

    annotated = with_expiry(rows, NOW, WINDOW)

    assert (annotated[0]["daysRemaining"], annotated[0]["status"]) == (10, "expiring")


def test_expiry_leaves_the_original_rows_alone() -> None:
    rows = credential_rows(registration(passwordCredentials=[secret("deploy", None)]))

    with_expiry(rows, NOW, WINDOW)

    assert "status" not in rows[0]


def test_a_row_with_no_end_date_is_unknown_not_a_failure() -> None:
    rows = credential_rows(registration(passwordCredentials=[secret("deploy", None)]))

    annotated = with_expiry(rows, NOW, WINDOW)

    assert (annotated[0]["daysRemaining"], annotated[0]["status"]) == (None, "unknown")


def test_every_status_is_assigned_from_the_same_moment() -> None:
    rows = credential_rows(
        registration(
            passwordCredentials=[
                secret("gone", "2026-10-01T12:00:00Z"),
                secret("soon", "2026-11-20T12:00:00Z"),
                secret("fine", "2028-05-12T09:00:00Z"),
            ]
        )
    )

    annotated = with_expiry(rows, NOW, WINDOW)

    assert {row["name"]: row["status"] for row in annotated} == {
        "gone": "expired",
        "soon": "expiring",
        "fine": "valid",
    }
