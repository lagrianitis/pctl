"""Unit tests for turning an application's credentials into rows.

Two things matter here. The rows must never carry more than the fields chosen for them,
since a Graph response can include a secret value or key material and a row that copied
whatever arrived would print it. And the dates must sort and parse the way Graph sends
them, including the seven fractional digits that `datetime` would refuse before 3.11.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pctl.azure.applications.common import credential_rows, parse_graph_time

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
