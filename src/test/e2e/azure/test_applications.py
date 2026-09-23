"""End-to-end: `pctl azure apps`, against Graph faked with respx.

An application has two GUIDs, `appId` and `id`, and they address different things. Most of
what is asserted here is that the right one is used for the right lookup, because getting
that wrong produces a confident "no such object" rather than a visible failure.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, filters, lines, ok

pytestmark = pytest.mark.e2e

APP_OBJECT_ID = "aaaaaaaa-1111-2222-3333-444444444444"
APP_CLIENT_ID = "8f468c48-e9ac-4dd7-973d-9704b9cdd56d"
SP_OBJECT_ID = "240c4d97-0d28-41f9-9047-2d028e6645e5"
ORPHAN_CLIENT_ID = "bbbbbbbb-1111-2222-3333-444444444444"
SCIM_APP = "Company Incident.io SCIM"

APP = {
    "id": APP_OBJECT_ID,
    "appId": APP_CLIENT_ID,
    "displayName": SCIM_APP,
    "signInAudience": "AzureADMyOrg",
    "publisherDomain": "example.com",
}
ORPHAN = {
    "id": "cccccccc-1111-2222-3333-444444444444",
    "appId": ORPHAN_CLIENT_ID,
    "displayName": "Company Registered Only",
    "signInAudience": "AzureADMyOrg",
}


@pytest.fixture
def tenant(graph: Any, seen: list[str]) -> Any:
    """Two registrations, one of which has no service principal in this tenant."""
    import httpx

    def applications(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        # Case-folded, because `$search` is case-insensitive at Graph and the tests use
        # lowercase terms like "incident" against a display name that capitalises it.
        # Matching case-sensitively made a search for "incident" return nothing.
        url = unquote_plus(str(request.url)).casefold()
        if APP_CLIENT_ID in url or "incident" in url or SCIM_APP.casefold() in url:
            return httpx.Response(200, json={"value": [APP]})
        if ORPHAN_CLIENT_ID in url or "registered only" in url:
            return httpx.Response(200, json={"value": [ORPHAN]})
        if "company" in url:
            # A prefix that matches both, so ambiguity is reachable.
            return httpx.Response(200, json={"value": [APP, ORPHAN]})
        return httpx.Response(200, json={"value": []})

    def principals(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url)).casefold()
        if APP_CLIENT_ID in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": SP_OBJECT_ID,
                            "appId": APP_CLIENT_ID,
                            "displayName": SCIM_APP,
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/applications/{APP_OBJECT_ID}").mock(
        return_value=httpx.Response(200, json=APP)
    )
    graph.get(f"{GRAPH}/applications").mock(side_effect=applications)
    graph.get(f"{GRAPH}/servicePrincipals").mock(side_effect=principals)
    return graph


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def test_list_streams_registrations(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "ndjson", "azure", "apps", "list", "--search", "incident"])
    )

    assert json.loads(lines(result.stdout)[0])["appId"] == APP_CLIENT_ID


def test_starts_with_becomes_a_display_name_filter(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "apps", "list", "--starts-with", "Company "]))

    assert filters(seen) == ["startswith(displayName,'Company ')"]


def test_the_default_columns_lead_with_the_client_id(runner: Any, cli: Any, tenant: Any) -> None:
    """appId is what you pivot on, so it belongs in the terminal view."""
    result = ok(runner.invoke(cli, ["-o", "csv", "azure", "apps", "list", "--search", "incident"]))

    assert lines(result.stdout)[0] == "displayName,appId,signInAudience,id"


# ---------------------------------------------------------------------------
# get: which GUID is which
# ---------------------------------------------------------------------------
def test_a_guid_is_tried_as_an_app_id_first(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    """The portal shows appId prominently, so it is the likelier thing to be holding."""
    payload = json.loads(
        ok(
            runner.invoke(cli, ["-o", "json", "azure", "apps", "get", "--app", APP_CLIENT_ID])
        ).stdout
    )

    assert payload["id"] == APP_OBJECT_ID
    assert filters(seen) == [f"appId eq '{APP_CLIENT_ID}'"]


def test_an_object_id_falls_back_to_direct_addressing(runner: Any, cli: Any, tenant: Any) -> None:
    """No appId matches an object ID, so the lookup retries /applications/{id}."""
    payload = json.loads(
        ok(
            runner.invoke(cli, ["-o", "json", "azure", "apps", "get", "--app", APP_OBJECT_ID])
        ).stdout
    )

    assert payload["appId"] == APP_CLIENT_ID


def test_a_display_name_uses_an_equality_filter(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "apps", "get", "--app", SCIM_APP]))

    assert filters(seen) == [f"displayName eq '{SCIM_APP}'"]


def test_an_ambiguous_display_name_is_refused(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(
        runner.invoke(cli, ["azure", "apps", "get", "--app", "Company", "--match", "prefix"]),
        2,
    )

    assert "2 application registrations match" in result.output


def test_an_unknown_name_exits_4(runner: Any, cli: Any, tenant: Any) -> None:
    result = failed(runner.invoke(cli, ["azure", "apps", "get", "--app", "no-such-app"]), 4)

    assert "no-such-app" in result.output


# ---------------------------------------------------------------------------
# get --with-sp: the appId join
# ---------------------------------------------------------------------------
def test_with_sp_attaches_the_service_principal(runner: Any, cli: Any, tenant: Any) -> None:
    payload = json.loads(
        ok(
            runner.invoke(
                cli,
                ["-o", "json", "azure", "apps", "get", "--app", SCIM_APP, "--with-sp"],
            )
        ).stdout
    )

    assert payload["servicePrincipalId"] == SP_OBJECT_ID
    assert payload["servicePrincipal"]["appId"] == APP_CLIENT_ID


def test_the_two_objects_have_different_ids(runner: Any, cli: Any, tenant: Any) -> None:
    """The whole point of --with-sp: one appId, two object IDs, easily confused."""
    payload = json.loads(
        ok(
            runner.invoke(
                cli,
                ["-o", "json", "azure", "apps", "get", "--app", SCIM_APP, "--with-sp"],
            )
        ).stdout
    )

    assert payload["id"] != payload["servicePrincipalId"]
    assert payload["appId"] == payload["servicePrincipal"]["appId"]


def test_the_service_principal_is_looked_up_by_app_id(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    """Never by object ID: the two differ, and that mistake returns nothing."""
    ok(runner.invoke(cli, ["azure", "apps", "get", "--app", SCIM_APP, "--with-sp"]))

    assert f"appId eq '{APP_CLIENT_ID}'" in filters(seen)
    assert f"appId eq '{APP_OBJECT_ID}'" not in filters(seen)


def test_a_registration_without_a_service_principal_is_reported(
    runner: Any, cli: Any, tenant: Any
) -> None:
    """Registered but not instantiated here, which is a real and confusing state."""
    result = ok(
        runner.invoke(
            cli,
            ["azure", "apps", "get", "--app", "Company Registered Only", "--with-sp"],
        )
    )

    assert "no service principal in this tenant" in result.stderr


def test_without_the_flag_no_service_principal_call_is_made(
    runner: Any, cli: Any, tenant: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "apps", "get", "--app", SCIM_APP]))

    assert not any("servicePrincipals" in url for url in seen)


# ---------------------------------------------------------------------------
# batches
# ---------------------------------------------------------------------------
def test_several_identifiers_resolve_concurrently(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "apps",
                "get",
                "--app",
                APP_CLIENT_ID,
                "--app",
                ORPHAN_CLIENT_ID,
            ],
        )
    )

    assert len(lines(result.stdout)) == 2


def test_ignore_missing_tolerates_an_unknown_identifier(runner: Any, cli: Any, tenant: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "apps",
                "get",
                "--app",
                APP_CLIENT_ID,
                "--app",
                "no-such-app",
                "--ignore-missing",
            ],
        )
    )

    assert len(lines(result.stdout)) == 1
