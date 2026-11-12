"""End-to-end: `pctl azure apps get-client-secrets`, against Graph faked with respx.

The listing is read from the application object itself, so the interesting assertions are
about what is asked for and what is allowed to come back out: the two credential
collections must be requested, and nothing beyond the chosen fields may be printed even
when the response carries a secret value or key material.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, filters, lines, ok

pytestmark = pytest.mark.e2e

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
APP_OBJECT_ID = "aaaaaaaa-1111-2222-3333-444444444444"
APP_CLIENT_ID = "8f468c48-e9ac-4dd7-973d-9704b9cdd56d"
APP_NAME = "ci-deploy-app"

APP = {
    "id": APP_OBJECT_ID,
    "appId": APP_CLIENT_ID,
    "displayName": APP_NAME,
    "passwordCredentials": [
        {
            "displayName": "later",
            "keyId": "key-later",
            "startDateTime": "2026-05-12T09:00:00Z",
            "endDateTime": "2028-05-12T09:00:00Z",
            "hint": "Dba",
            "secretText": "LEAKED-SECRET-VALUE",
            "customKeyIdentifier": None,
        },
        {
            "displayName": "sooner",
            "keyId": "key-sooner",
            "startDateTime": "2025-04-20T09:00:00Z",
            "endDateTime": "2027-04-20T09:00:00.0000000Z",
            "hint": "paN",
            "secretText": None,
        },
    ],
    "keyCredentials": [],
}
EXPIRING_APP = {
    "id": "eeeeeeee-1111-2222-3333-444444444444",
    "appId": "ffffffff-1111-2222-3333-444444444444",
    "displayName": "ci-expiring",
    "passwordCredentials": [
        {
            "displayName": "gone",
            "keyId": "key-gone",
            "endDateTime": "2026-10-01T12:00:00Z",
            "hint": "xyz",
        },
        {
            "displayName": "soon",
            "keyId": "key-soon",
            "endDateTime": "2026-11-20T12:00:00Z",
            "hint": "uvw",
        },
        {
            "displayName": "fine",
            "keyId": "key-fine",
            "endDateTime": "2028-05-12T09:00:00Z",
            "hint": "rst",
        },
    ],
    "keyCredentials": [],
}
SOON_APP = {
    "id": "11111111-1111-2222-3333-444444444444",
    "appId": "22222222-1111-2222-3333-444444444444",
    "displayName": "ci-soon",
    "passwordCredentials": [
        {"displayName": "soon", "keyId": "key-soon", "endDateTime": "2026-11-20T12:00:00Z"}
    ],
}
GONE_APP = {
    "id": "33333333-1111-2222-3333-444444444444",
    "appId": "44444444-1111-2222-3333-444444444444",
    "displayName": "ci-gone",
    "passwordCredentials": [
        {"displayName": "gone", "keyId": "key-gone", "endDateTime": "2026-10-01T12:00:00Z"}
    ],
}
BARE_APP = {
    "id": "bbbbbbbb-1111-2222-3333-444444444444",
    "appId": "cccccccc-1111-2222-3333-444444444444",
    "displayName": "bare",
}
OTHER_APP = {**APP, "id": "dddddddd-1111-2222-3333-444444444444", "displayName": "ci-deploy-other"}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Pin "now", so a status and a number of days never depend on the day the test runs.

    Autouse because every credential here has an end date, and an unpinned clock would let
    a test that passes today fail the day one of them lapses.
    """
    monkeypatch.setattr("pctl.azure.applications.get_client_secrets.utcnow", lambda: NOW)
    return NOW


@pytest.fixture
def tenant(graph: Any, seen: list[str]) -> Any:
    """Registrations with credentials in each state, one with none, and a prefix matching two."""
    import httpx

    def applications(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url)).casefold()
        if "'bare'" in url:
            return httpx.Response(200, json={"value": [BARE_APP]})
        for name, registration in {
            "ci-expiring": EXPIRING_APP,
            "ci-soon": SOON_APP,
            "ci-gone": GONE_APP,
        }.items():
            if f"'{name}'" in url:
                return httpx.Response(200, json={"value": [registration]})
        if APP_CLIENT_ID in url or f"'{APP_NAME}'" in url:
            return httpx.Response(200, json={"value": [APP]})
        if "startswith" in url and "'ci-deploy-'" in url:
            return httpx.Response(200, json={"value": [APP, OTHER_APP]})
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/applications").mock(side_effect=applications)
    return graph


def credentials(runner: Any, cli: Any, *args: str, output: str = "ndjson") -> Any:
    return runner.invoke(cli, ["-o", output, "azure", "apps", "get-client-secrets", *args])


def test_every_secret_is_a_row_soonest_first(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", APP_NAME))

    rows = [json.loads(line) for line in lines(result.stdout)]
    assert [row["name"] for row in rows] == ["sooner", "later"]
    assert {row["type"] for row in rows} == {"secret"}


def test_a_row_carries_the_dates_the_key_id_and_the_app(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", APP_NAME))

    row = json.loads(lines(result.stdout)[0])
    assert row["keyId"] == "key-sooner"
    assert row["startDateTime"] == "2025-04-20T09:00:00Z"
    assert row["endDateTime"] == "2027-04-20T09:00:00.0000000Z"
    assert (row["app"], row["appId"]) == (APP_NAME, APP_CLIENT_ID)
    assert row["hint"] == "paN"


def test_json_is_a_single_document(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", APP_NAME, output="json"))

    assert [row["name"] for row in json.loads(result.stdout)] == ["sooner", "later"]


def test_the_default_columns_are_the_ones_that_answer_the_question(
    runner: Any, cli: Any, tenant: Any
) -> None:
    result = ok(credentials(runner, cli, "--app-name", APP_NAME, output="csv"))

    assert lines(result.stdout)[0] == "type,name,status,daysRemaining,endDateTime,keyId"


def test_columns_can_be_chosen(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", APP_NAME, "-c", "name,hint", output="csv"))

    assert lines(result.stdout) == ["name,hint", "sooner,paN", "later,Dba"]


def test_both_credential_collections_are_requested(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    ok(credentials(runner, cli, "--app-name", APP_NAME))

    asked = unquote_plus(seen[0])
    assert "passwordCredentials" in asked
    assert "keyCredentials" in asked


@pytest.mark.parametrize("output", ["table", "json", "ndjson", "csv"])
def test_a_secret_value_in_the_response_is_never_printed(
    runner: Any, cli: Any, tenant: Any, output: str
) -> None:
    """Graph only sends this at creation, but the command must not depend on that."""
    result = ok(credentials(runner, cli, "--app-name", APP_NAME, output=output))

    assert "LEAKED-SECRET-VALUE" not in result.output


def test_an_app_id_is_looked_up_by_app_id_alone(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    result = ok(credentials(runner, cli, "--app-id", APP_CLIENT_ID))

    assert filters(seen) == [f"appId eq '{APP_CLIENT_ID}'"]
    assert [json.loads(line)["name"] for line in lines(result.stdout)] == ["sooner", "later"]


def test_an_app_name_is_looked_up_by_display_name(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    ok(credentials(runner, cli, "--app-name", APP_NAME))

    assert filters(seen) == [f"displayName eq '{APP_NAME}'"]


def test_an_unknown_app_id_exits_4(runner: Any, cli: Any, tenant: Any) -> None:
    failed(credentials(runner, cli, "--app-id", "99999999-9999-9999-9999-999999999999"), 4)


def test_an_app_id_that_is_not_a_guid_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(credentials(runner, cli, "--app-id", APP_NAME), 2)

    assert "must be a GUID" in result.output


def test_both_flags_are_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(credentials(runner, cli, "--app-name", APP_NAME, "--app-id", APP_CLIENT_ID), 2)

    assert "exactly one of --app-name or --app-id" in result.output


def test_neither_flag_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(credentials(runner, cli), 2)

    assert "exactly one of --app-name or --app-id" in result.output


def test_an_ambiguous_name_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    """Two registrations match, and acting on the wrong one's secrets is the risk."""
    result = failed(credentials(runner, cli, "--app-name", "ci-deploy-", "--match", "prefix"), 2)

    assert "Pass --app-id" in result.output


def test_a_name_that_matches_nothing_exits_4(runner: Any, cli: Any, tenant: Any) -> None:
    failed(credentials(runner, cli, "--app-name", "no-such-app"), 4)


def test_an_app_with_no_credentials_exits_0_and_says_so(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", "bare"))

    assert result.stdout.strip() == ""
    assert "has no client secrets or certificates" in result.stderr


def statuses(stdout: str) -> dict[str, tuple[int, str]]:
    """Name to (days remaining, status), read from ndjson."""
    rows = [json.loads(line) for line in lines(stdout)]
    return {row["name"]: (row["daysRemaining"], row["status"]) for row in rows}


def test_each_credential_shows_its_days_and_status(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring"))

    assert statuses(result.stdout) == {
        "gone": (-42, "expired"),
        "soon": (8, "expiring"),
        "fine": (546, "valid"),
    }


def test_the_credentials_are_listed_in_the_order_they_end(
    runner: Any, cli: Any, tenant: Any
) -> None:
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring"))

    assert [json.loads(line)["name"] for line in lines(result.stdout)] == ["gone", "soon", "fine"]


def test_the_default_window_is_thirty_days(runner: Any, cli: Any, tenant: Any) -> None:
    """Eight days away is inside it, so a bare invocation already flags it."""
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring"))

    assert statuses(result.stdout)["soon"][1] == "expiring"


def test_a_narrower_window_stops_counting_it_as_expiring(
    runner: Any, cli: Any, tenant: Any
) -> None:
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring", "--expiring-within", "5"))

    assert statuses(result.stdout)["soon"][1] == "valid"


def test_a_wider_window_catches_a_later_one(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring", "--expiring-within", "600"))

    assert statuses(result.stdout)["fine"][1] == "expiring"


def test_the_output_is_the_same_every_time_the_clock_is_fixed(
    runner: Any, cli: Any, tenant: Any
) -> None:
    first = ok(credentials(runner, cli, "--app-name", "ci-expiring", output="json")).stdout
    second = ok(credentials(runner, cli, "--app-name", "ci-expiring", output="json")).stdout

    assert first == second


def test_a_table_shows_the_status_and_days(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring", output="table"))

    assert "expired" in result.stdout
    assert "-42" in result.stdout


def test_lapsed_credentials_do_not_fail_the_command_by_default(
    runner: Any, cli: Any, tenant: Any
) -> None:
    """Listing is not a check unless asked to be, or every report would be a failure."""
    result = ok(credentials(runner, cli, "--app-name", "ci-expiring"))

    assert "1 expired and 1 expiring within 30 days, of 3 credential(s)" in result.stderr


def test_the_flag_fails_with_exit_6_when_something_has_lapsed(
    runner: Any, cli: Any, tenant: Any
) -> None:
    result = failed(credentials(runner, cli, "--app-name", "ci-expiring", "--fail-on-expiry"), 6)

    assert "1 expired and 1 expiring within 30 days" in result.output


def test_the_flag_still_lists_everything_before_failing(runner: Any, cli: Any, tenant: Any) -> None:
    """A failed check with no detail would send you to the portal to find out which."""
    result = failed(credentials(runner, cli, "--app-name", "ci-expiring", "--fail-on-expiry"), 6)

    assert set(statuses(result.stdout)) == {"gone", "soon", "fine"}


def test_the_flag_fails_for_a_credential_that_is_only_expiring(
    runner: Any, cli: Any, tenant: Any
) -> None:
    """Nothing has lapsed yet, which is exactly when a pipeline wants to hear about it."""
    failed(credentials(runner, cli, "--app-name", "ci-soon", "--fail-on-expiry"), 6)


def test_the_flag_fails_for_a_credential_that_has_only_lapsed(
    runner: Any, cli: Any, tenant: Any
) -> None:
    failed(credentials(runner, cli, "--app-name", "ci-gone", "--fail-on-expiry"), 6)


def test_the_flag_passes_when_every_credential_is_in_date(
    runner: Any, cli: Any, tenant: Any
) -> None:
    ok(credentials(runner, cli, "--app-name", APP_NAME, "--fail-on-expiry"))


def test_the_flag_passes_for_an_app_with_no_credentials(runner: Any, cli: Any, tenant: Any) -> None:
    ok(credentials(runner, cli, "--app-name", "bare", "--fail-on-expiry"))


def test_a_window_wide_enough_makes_the_flag_fail_on_a_healthy_app(
    runner: Any, cli: Any, tenant: Any
) -> None:
    """APP's soonest secret ends in April 2027, about 160 days after the pinned clock."""
    failed(
        credentials(
            runner, cli, "--app-name", APP_NAME, "--expiring-within", "200", "--fail-on-expiry"
        ),
        6,
    )
