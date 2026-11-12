"""End-to-end: `pctl azure apps remove-client-secret`, against Graph faked with respx.

Removal cannot be undone, so what is asserted is the guard: a secret with plenty of time
left is not removed without `--force`, one that has lapsed or is about to is, the boundary
sits where the documentation says it does, only a key ID can name the secret, and nothing is
sent to Graph when the command refuses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from helpers import GRAPH, failed, ok, reply

pytestmark = pytest.mark.e2e

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
APP_OBJECT_ID = "aaaaaaaa-1111-2222-3333-444444444444"
APP_CLIENT_ID = "8f468c48-e9ac-4dd7-973d-9704b9cdd56d"
APP_NAME = "ci-deploy-app"
REMOVE_PASSWORD = f"{GRAPH}/applications/{APP_OBJECT_ID}/removePassword"
LAPSED = "2026-10-01T00:00:00Z"
SOON = "2026-11-20T12:00:00Z"
AT_THE_EDGE = "2026-12-12T12:00:00Z"
JUST_BEYOND = "2026-12-12T12:00:01Z"
FAR = "2027-06-01T00:00:00Z"


def secret(name: str, key_id: str, end: str | None) -> dict[str, Any]:
    return {"displayName": name, "keyId": key_id, "endDateTime": end, "hint": "abc"}


APP = {
    "id": APP_OBJECT_ID,
    "appId": APP_CLIENT_ID,
    "displayName": APP_NAME,
    "passwordCredentials": [
        secret("lapsed", "key-lapsed", LAPSED),
        secret("soon", "key-soon", SOON),
        secret("edge", "key-edge", AT_THE_EDGE),
        secret("beyond", "key-beyond", JUST_BEYOND),
        secret("far", "key-far", FAR),
        secret("undated", "key-undated", None),
        secret("twin", "key-twin-far", FAR),
        secret("twin", "key-twin-soon", SOON),
    ],
    "keyCredentials": [{"displayName": "signing", "keyId": "key-cert", "endDateTime": FAR}],
}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Pin "now", because the whole rule is a distance from it."""
    monkeypatch.setattr("pctl.azure.applications.remove_client_secret.utcnow", lambda: NOW)
    return NOW


@pytest.fixture
def tenant(graph: Any) -> Any:
    """An app holding a secret in each state the rule distinguishes, and a certificate."""
    import httpx

    graph.get(f"{GRAPH}/applications", name="apps").mock(
        return_value=httpx.Response(200, json={"value": [APP]})
    )
    graph.post(REMOVE_PASSWORD, name="remove").mock(return_value=httpx.Response(204))
    return graph


def remove(
    runner: Any,
    cli: Any,
    *args: str,
    app_flags: tuple[str, ...] = ("--app-name", APP_NAME),
) -> Any:
    return runner.invoke(
        cli, ["-o", "json", "azure", "apps", "remove-client-secret", *app_flags, *args]
    )


def removed_key(route: Any) -> str:
    return str(json.loads(route.calls.last.request.content)["keyId"])


@pytest.mark.parametrize("key_id", ["key-lapsed", "key-soon", "key-edge"])
def test_a_secret_that_is_lapsed_or_within_the_window_needs_no_force(
    runner: Any, cli: Any, tenant: Any, key_id: str
) -> None:
    ok(remove(runner, cli, "--key-id", key_id))

    assert removed_key(tenant["remove"]) == key_id


def test_the_window_is_inclusive_at_thirty_days(runner: Any, cli: Any, tenant: Any) -> None:
    """Exactly 30 days left counts as expiring, the same as `get-client-secrets` says."""
    ok(remove(runner, cli, "--key-id", "key-edge"))

    assert tenant["remove"].call_count == 1


def test_force_is_harmless_when_it_is_not_needed(runner: Any, cli: Any, tenant: Any) -> None:
    ok(remove(runner, cli, "--key-id", "key-soon", "--force"))

    assert removed_key(tenant["remove"]) == "key-soon"


@pytest.mark.parametrize("key_id", ["key-beyond", "key-far", "key-undated"])
def test_a_secret_with_time_left_is_refused_without_force(
    runner: Any, cli: Any, tenant: Any, key_id: str
) -> None:
    result = failed(remove(runner, cli, "--key-id", key_id), 2)

    assert "Pass --force" in result.output
    assert tenant["remove"].call_count == 0


def test_one_second_beyond_the_window_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    failed(remove(runner, cli, "--key-id", "key-beyond"), 2)

    assert tenant["remove"].call_count == 0


def test_the_refusal_says_how_long_is_left(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(remove(runner, cli, "--key-id", "key-far"), 2)

    # 2026-11-12T12:00Z to 2027-06-01T00:00Z is 200.5 days, rounded down.
    assert "still has 200 days left" in result.output


def test_a_secret_with_no_end_date_says_so(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(remove(runner, cli, "--key-id", "key-undated"), 2)

    assert "has no end date" in result.output


@pytest.mark.parametrize("key_id", ["key-beyond", "key-far", "key-undated"])
def test_force_removes_a_secret_with_time_left(
    runner: Any, cli: Any, tenant: Any, key_id: str
) -> None:
    ok(remove(runner, cli, "--key-id", key_id, "--force"))

    assert removed_key(tenant["remove"]) == key_id


def test_the_key_id_is_matched_without_regard_to_case(runner: Any, cli: Any, tenant: Any) -> None:
    ok(remove(runner, cli, "--key-id", "KEY-SOON"))

    assert removed_key(tenant["remove"]) == "key-soon"


def test_two_secrets_of_the_same_name_are_told_apart_by_key_id(
    runner: Any, cli: Any, tenant: Any
) -> None:
    ok(remove(runner, cli, "--key-id", "key-twin-soon"))

    assert removed_key(tenant["remove"]) == "key-twin-soon"


def test_a_name_is_not_accepted(runner: Any, cli: Any, tenant: Any) -> None:
    """Names are not unique and removal is permanent, so there is no flag for one."""
    result = failed(remove(runner, cli, "--name", "soon"), 2)

    assert "No such option" in result.output
    assert tenant["remove"].call_count == 0


def test_a_name_given_as_the_key_id_matches_nothing(runner: Any, cli: Any, tenant: Any) -> None:
    failed(remove(runner, cli, "--key-id", "soon"), 4)

    assert tenant["remove"].call_count == 0


def test_an_unknown_key_id_exits_4(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(remove(runner, cli, "--key-id", "no-such-key"), 4)

    assert "no client secret with key ID no-such-key" in result.output
    assert tenant["remove"].call_count == 0


def test_a_certificate_is_not_removed(runner: Any, cli: Any, tenant: Any) -> None:
    """Graph wants proof of possession to remove one, which this command cannot give."""
    result = failed(remove(runner, cli, "--key-id", "key-cert", "--force"), 2)

    assert "is a certificate" in result.output
    assert tenant["remove"].call_count == 0


def test_a_key_id_is_required(runner: Any, cli: Any, tenant: Any) -> None:
    failed(remove(runner, cli), 2)

    assert tenant["token"].call_count == 0


def test_the_app_must_be_named(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(remove(runner, cli, "--key-id", "key-soon", app_flags=()), 2)

    assert "exactly one of --app-name or --app-id" in result.output
    assert tenant["token"].call_count == 0


def test_the_app_can_be_named_by_app_id(runner: Any, cli: Any, tenant: Any) -> None:
    ok(remove(runner, cli, "--key-id", "key-soon", app_flags=("--app-id", APP_CLIENT_ID)))

    assert removed_key(tenant["remove"]) == "key-soon"


def test_the_report_says_what_was_removed(runner: Any, cli: Any, tenant: Any) -> None:
    record = json.loads(ok(remove(runner, cli, "--key-id", "key-soon")).stdout)

    assert record == {
        "app": APP_NAME,
        "appId": APP_CLIENT_ID,
        "name": "soon",
        "keyId": "key-soon",
        "endDateTime": SOON,
        "removed": True,
    }


def test_a_server_error_exits_5(runner: Any, cli: Any, tenant: Any, no_sleep: None) -> None:
    tenant["remove"].mock(return_value=reply(500))

    failed(remove(runner, cli, "--key-id", "key-soon"), 5)
