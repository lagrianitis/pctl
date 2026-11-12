"""End-to-end: `pctl azure apps add-client-secret`, Graph on respx, Secrets Manager on moto.

A new client secret's value is shown by Graph once. Nearly everything asserted here is about
that: that no secret is created unless its value has somewhere to go, that the destination
is vetted before the secret exists, that a failure to store it removes the secret again, and
that the value never reaches output it was not asked to reach.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from helpers import GRAPH, failed, lines, ok, reply, unreachable

pytestmark = pytest.mark.e2e

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
# 180 days after NOW, which is the default lifetime, and 90 days after it.
END_DEFAULT = "2027-05-11T12:00:00Z"
END_90 = "2027-02-10T12:00:00Z"

APP_OBJECT_ID = "aaaaaaaa-1111-2222-3333-444444444444"
APP_CLIENT_ID = "8f468c48-e9ac-4dd7-973d-9704b9cdd56d"
APP_NAME = "ci-deploy-app"
NEW_KEY_ID = "new-key-id"
SECRET_VALUE = "NEW-SECRET-VALUE-9f3a"
TARGET = "platform/app-credentials"
BY_ID = ("--app-id", APP_CLIENT_ID)
KEY_ID = "ci_deploy_app_terraform2_client_id"
KEY_SECRET = "ci_deploy_app_terraform2_client_secret"
KEY_EXP = "ci_deploy_app_terraform2_client_exp_date"

APP = {
    "id": APP_OBJECT_ID,
    "appId": APP_CLIENT_ID,
    "displayName": APP_NAME,
    "passwordCredentials": [
        {"displayName": "existing", "keyId": "key-existing", "endDateTime": "2028-01-01T00:00:00Z"}
    ],
    "keyCredentials": [],
}
ADD_PASSWORD = f"{GRAPH}/applications/{APP_OBJECT_ID}/addPassword"
REMOVE_PASSWORD = f"{GRAPH}/applications/{APP_OBJECT_ID}/removePassword"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Pin "now", so the end date a command asks for is the same every day."""
    monkeypatch.setattr("pctl.azure.applications.add_client_secret.utcnow", lambda: NOW)
    return NOW


@pytest.fixture
def tenant(graph: Any) -> Any:
    """An app registration, with Graph creating a secret that ends when it was asked to."""
    import httpx

    def add_password(request: httpx.Request) -> httpx.Response:
        asked = json.loads(request.content)["passwordCredential"]
        return httpx.Response(
            200,
            json={
                "keyId": NEW_KEY_ID,
                "displayName": asked["displayName"],
                "endDateTime": asked["endDateTime"],
                "secretText": SECRET_VALUE,
            },
        )

    graph.get(f"{GRAPH}/applications", name="apps").mock(
        return_value=httpx.Response(200, json={"value": [APP]})
    )
    graph.post(ADD_PASSWORD, name="add").mock(side_effect=add_password)
    graph.post(REMOVE_PASSWORD, name="remove").mock(return_value=httpx.Response(204))
    return graph


def add(
    runner: Any,
    cli: Any,
    *args: str,
    name: str = "terraform2",
    app_flags: tuple[str, ...] = ("--app-name", APP_NAME),
) -> Any:
    return runner.invoke(
        cli,
        ["-o", "json", "azure", "apps", "add-client-secret", *app_flags, "--name", name, *args],
    )


def sent_body(route: Any) -> dict[str, Any]:
    return dict(json.loads(route.calls.last.request.content))


def test_the_three_values_are_added_under_the_named_keys(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    ok(add(runner, cli, "--store-in", TARGET))

    assert secrets_manager.read(TARGET) == {
        KEY_ID: APP_CLIENT_ID,
        KEY_SECRET: SECRET_VALUE,
        KEY_EXP: END_DEFAULT,
    }


def test_every_other_key_in_the_secret_is_kept(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {"unrelated": "keep me", "other_app_x_client_id": "abc"})

    ok(add(runner, cli, "--store-in", TARGET))

    stored = secrets_manager.read(TARGET)
    assert stored["unrelated"] == "keep me"
    assert stored["other_app_x_client_id"] == "abc"
    assert stored[KEY_SECRET] == SECRET_VALUE


def test_the_report_names_where_it_went_without_the_value(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    result = ok(add(runner, cli, "--store-in", TARGET))

    record = json.loads(result.stdout)
    assert record["storedIn"] == TARGET
    assert record["storedKeys"] == [KEY_ID, KEY_SECRET, KEY_EXP]
    assert record["keyId"] == NEW_KEY_ID
    assert "secret" not in record


@pytest.mark.parametrize("verbose", [[], ["-v"]])
def test_the_value_is_never_printed_unless_asked_for(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any, verbose: list[str]
) -> None:
    """Not in the report, not in the summary, and not in the -v log either."""
    secrets_manager.create(TARGET, {})

    command = ["azure", "apps", "add-client-secret", "--app-name", APP_NAME, "--name", "terraform2"]
    result = ok(runner.invoke(cli, [*verbose, *command, "--store-in", TARGET]))

    assert SECRET_VALUE not in result.output


def test_the_secret_is_created_with_the_requested_name_and_default_end(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    ok(add(runner, cli, "--store-in", TARGET))

    assert sent_body(tenant["add"]) == {
        "passwordCredential": {"displayName": "terraform2", "endDateTime": END_DEFAULT}
    }


def test_the_lifetime_can_be_chosen(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    ok(add(runner, cli, "--store-in", TARGET, "--valid-for-days", "90"))

    assert sent_body(tenant["add"])["passwordCredential"]["endDateTime"] == END_90


def test_the_stored_expiry_is_the_one_graph_reported(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    """Graph may clamp the lifetime to the tenant's policy, and that is the real end date."""
    import httpx

    secrets_manager.create(TARGET, {})
    tenant["add"].mock(
        return_value=httpx.Response(
            200,
            json={
                "keyId": NEW_KEY_ID,
                "endDateTime": "2027-01-01T00:00:00Z",
                "secretText": SECRET_VALUE,
            },
        )
    )

    ok(add(runner, cli, "--store-in", TARGET))

    assert secrets_manager.read(TARGET)[KEY_EXP] == "2027-01-01T00:00:00Z"


def test_show_secret_prints_the_value_once(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(add(runner, cli, "--show-secret"))

    assert json.loads(result.stdout)["secret"] == SECRET_VALUE
    assert result.output.count(SECRET_VALUE) == 1


def test_show_secret_alone_stores_nothing(runner: Any, cli: Any, tenant: Any) -> None:
    record = json.loads(ok(add(runner, cli, "--show-secret")).stdout)

    assert (record["storedIn"], record["storedKeys"]) == (None, None)


def test_both_flags_store_and_show(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    result = ok(add(runner, cli, "--store-in", TARGET, "--show-secret"))

    assert json.loads(result.stdout)["secret"] == SECRET_VALUE
    assert secrets_manager.read(TARGET)[KEY_SECRET] == SECRET_VALUE


def test_no_destination_is_refused_before_graph_is_called(
    runner: Any, cli: Any, tenant: Any
) -> None:
    """A secret whose value could not be kept would be created and instantly lost."""
    result = failed(add(runner, cli), 2)

    assert "would be lost" in result.output
    assert tenant["add"].call_count == 0
    assert tenant["token"].call_count == 0


def test_a_name_the_app_already_uses_is_refused(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    """Creating is not idempotent, so a repeat run would add a second live secret."""
    secrets_manager.create(TARGET, {})

    result = failed(add(runner, cli, "--store-in", TARGET, name="Existing"), 2)

    assert "already has a client secret named" in result.output
    assert tenant["add"].call_count == 0


def test_a_missing_target_is_found_out_before_the_secret_is_created(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    result = failed(add(runner, cli, "--store-in", "no/such/secret"), 2)

    assert "was not found" in result.output
    assert tenant["add"].call_count == 0


def test_a_target_that_is_not_a_json_object_is_refused(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, "just a string")

    failed(add(runner, cli, "--store-in", TARGET), 2)

    assert tenant["add"].call_count == 0


def test_a_target_scheduled_for_deletion_is_refused(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})
    secrets_manager.client.delete_secret(SecretId=TARGET, RecoveryWindowInDays=7)

    result = failed(add(runner, cli, "--store-in", TARGET), 2)

    assert "scheduled for deletion" in result.output
    assert tenant["add"].call_count == 0


def test_existing_keys_are_refused_without_overwrite(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {KEY_SECRET: "old-value"})

    result = failed(add(runner, cli, "--store-in", TARGET), 2)

    assert KEY_SECRET in result.output
    assert tenant["add"].call_count == 0
    assert secrets_manager.read(TARGET) == {KEY_SECRET: "old-value"}


def test_overwrite_replaces_the_keys_it_names(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {KEY_SECRET: "old-value", "unrelated": "keep"})

    ok(add(runner, cli, "--store-in", TARGET, "--overwrite"))

    stored = secrets_manager.read(TARGET)
    assert stored[KEY_SECRET] == SECRET_VALUE
    assert stored["unrelated"] == "keep"


@pytest.fixture
def failing_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the destination pass its checks, then fail the write itself."""
    from pctl.errors import UpstreamError
    from pctl.secrets import SecretObject

    def refuse(self: SecretObject, entries: Any, *, overwrite: bool) -> None:
        raise UpstreamError("Could not write secret: access denied")

    monkeypatch.setattr(SecretObject, "add", refuse)


def test_a_failed_write_removes_the_new_secret_again(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any, failing_write: None
) -> None:
    secrets_manager.create(TARGET, {})

    result = failed(add(runner, cli, "--store-in", TARGET), 5)

    assert "was removed again" in result.output
    assert sent_body(tenant["remove"]) == {"keyId": NEW_KEY_ID}


def test_a_failed_removal_names_the_key_to_remove_by_hand(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any, failing_write: None, no_sleep: None
) -> None:
    secrets_manager.create(TARGET, {})
    tenant["remove"].mock(return_value=reply(500))

    result = failed(add(runner, cli, "--store-in", TARGET), 5)

    assert NEW_KEY_ID in result.output
    assert "nobody holds its value" in result.output


def test_the_value_is_not_in_the_failure_message(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any, failing_write: None
) -> None:
    secrets_manager.create(TARGET, {})

    result = failed(add(runner, cli, "--store-in", TARGET), 5)

    assert SECRET_VALUE not in result.output


def test_a_response_with_no_value_is_undone(runner: Any, cli: Any, tenant: Any) -> None:
    """If Graph made a secret but sent nothing to keep, it must not be left live."""
    tenant["add"].mock(return_value=reply(200, json={"keyId": NEW_KEY_ID}))

    failed(add(runner, cli, "--show-secret"), 5)

    assert tenant["remove"].call_count == 1


def test_a_server_error_is_not_retried(runner: Any, cli: Any, tenant: Any, no_sleep: None) -> None:
    """After a 500 the secret may or may not exist; sending again could make two."""
    tenant["add"].mock(return_value=reply(500))

    result = failed(add(runner, cli, "--show-secret"), 5)

    assert tenant["add"].call_count == 1
    assert "may or may not have been applied" in result.output


def test_a_dropped_connection_is_not_retried(
    runner: Any, cli: Any, tenant: Any, no_sleep: None
) -> None:
    tenant["add"].mock(side_effect=unreachable())

    result = failed(add(runner, cli, "--show-secret"), 5)

    assert tenant["add"].call_count == 1
    assert "may or may not have been applied" in result.output


def test_throttling_is_retried_because_it_means_refused(
    runner: Any, cli: Any, tenant: Any, no_sleep: None
) -> None:
    """A 429 means the request was not applied, so sending it again is safe."""
    tenant["add"].mock(
        side_effect=[
            reply(429, headers={"Retry-After": "0"}),
            reply(
                200,
                json={"keyId": NEW_KEY_ID, "endDateTime": END_DEFAULT, "secretText": SECRET_VALUE},
            ),
        ]
    )

    result = ok(add(runner, cli, "--show-secret"))

    assert tenant["add"].call_count == 2
    assert json.loads(lines(result.stdout)[0])["secret"] == SECRET_VALUE


def looked_up_with(route: Any) -> str:
    """The decoded query of the last request to the applications collection."""
    from urllib.parse import unquote_plus

    return unquote_plus(str(route.calls.last.request.url))


def test_the_app_name_is_looked_up_by_display_name(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    ok(add(runner, cli, "--store-in", TARGET))

    assert f"displayName eq '{APP_NAME}'" in looked_up_with(tenant["apps"])


def test_the_app_id_skips_the_display_name_search(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    secrets_manager.create(TARGET, {})

    ok(add(runner, cli, "--store-in", TARGET, app_flags=BY_ID))

    assert tenant["apps"].call_count == 1
    assert f"appId eq '{APP_CLIENT_ID}'" in looked_up_with(tenant["apps"])
    assert "displayName eq" not in looked_up_with(tenant["apps"])


def test_the_app_id_gives_the_same_keys_as_the_name(
    runner: Any, cli: Any, tenant: Any, secrets_manager: Any
) -> None:
    """The keys are named from the registration's display name, however it was found."""
    secrets_manager.create(TARGET, {})

    ok(add(runner, cli, "--store-in", TARGET, app_flags=BY_ID))

    assert set(secrets_manager.read(TARGET)) == {KEY_ID, KEY_SECRET, KEY_EXP}


def test_both_flags_are_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(
        add(runner, cli, "--show-secret", app_flags=("--app-name", APP_NAME, *BY_ID)), 2
    )

    assert "exactly one of --app-name or --app-id" in result.output
    assert tenant["token"].call_count == 0


def test_neither_flag_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(add(runner, cli, "--show-secret", app_flags=()), 2)

    assert "exactly one of --app-name or --app-id" in result.output
    assert tenant["token"].call_count == 0


def test_an_app_id_that_is_not_a_guid_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(add(runner, cli, "--show-secret", app_flags=("--app-id", "ci-deploy-app")), 2)

    assert "must be a GUID" in result.output
    assert tenant["add"].call_count == 0


def test_an_unknown_app_id_is_not_found(runner: Any, cli: Any, tenant: Any) -> None:
    tenant["apps"].mock(return_value=reply(200, json={"value": []}))

    failed(add(runner, cli, "--show-secret", app_flags=BY_ID), 4)

    assert tenant["add"].call_count == 0
