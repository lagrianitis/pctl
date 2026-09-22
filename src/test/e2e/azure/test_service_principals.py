"""End-to-end: `pctl azure sp`, against Graph faked with respx.

The interesting behaviour is not the listing, it is the two things a user gets wrong:
which direction an app role assignment points, and that `appRoleId` is a GUID nobody
can read. Both are asserted here through the real command path.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, filters, lines, ok

pytestmark = pytest.mark.e2e

SP_ID = "sp-0001"
SCIM_APP = "Company Incident.io SCIM"
ROLE_ID = "11111111-2222-3333-4444-555555555555"
DEFAULT_ACCESS = "00000000-0000-0000-0000-000000000000"


def _sp(name: str = SCIM_APP, sp_id: str = SP_ID) -> dict[str, Any]:
    return {
        "id": sp_id,
        "displayName": name,
        "appId": "app-guid-0001",
        "servicePrincipalType": "Application",
        "accountEnabled": True,
    }


def _assignment(principal: str, *, role: str = ROLE_ID, kind: str = "Group") -> dict[str, Any]:
    return {
        "id": f"assignment-{principal}",
        "principalDisplayName": principal,
        "principalType": kind,
        "appRoleId": role,
        "createdDateTime": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def scim_app(graph: Any, seen: list[str]) -> Any:
    """Graph routes for one Enterprise Application and its assignments."""
    import httpx

    graph.get(f"{GRAPH}/servicePrincipals/{SP_ID}/appRoleAssignedTo").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    _assignment("AWS Platform Admins"),
                    _assignment("Ann Example", kind="User", role=DEFAULT_ACCESS),
                ]
            },
        )
    )
    graph.get(f"{GRAPH}/servicePrincipals/{SP_ID}/appRoleAssignments").mock(
        return_value=httpx.Response(
            200, json={"value": [_assignment(SCIM_APP, kind="ServicePrincipal")]}
        )
    )
    graph.get(f"{GRAPH}/servicePrincipals/{SP_ID}").mock(
        return_value=httpx.Response(
            200,
            json={"appRoles": [{"id": ROLE_ID, "displayName": "User", "value": "User"}]},
        )
    )

    def by_name(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url))
        if "incident" in url.casefold() or SCIM_APP in url:
            return httpx.Response(200, json={"value": [_sp()]})
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/servicePrincipals").mock(side_effect=by_name)
    return graph


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
def test_search_sends_the_advanced_query_parameters(
    runner: Any, cli: Any, scim_app: Any, seen: list[str]
) -> None:
    """This is the request shape the feature was specified against."""
    ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "list", "--search", "incident.io"]))

    url = unquote_plus(seen[-1])
    assert '$search="displayName:incident.io"' in url
    assert "$count=true" in url


def test_app_id_becomes_an_equality_filter(
    runner: Any, cli: Any, scim_app: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "sp", "list", "--app-id", "app-guid-0001"]))

    assert filters(seen) == ["appId eq 'app-guid-0001'"]


def test_list_streams_service_principals(runner: Any, cli: Any, scim_app: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "list", "--search", "incident"]))

    assert json.loads(lines(result.stdout)[0])["displayName"] == SCIM_APP


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------
def test_get_resolves_a_long_display_name_by_substring(
    runner: Any, cli: Any, scim_app: Any
) -> None:
    """The default match mode is search, so a fragment is enough."""
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "sp", "get", "incident"])).stdout
    )

    assert payload["displayName"] == SCIM_APP
    assert payload["appId"] == "app-guid-0001"


def test_get_can_attach_the_assignments(runner: Any, cli: Any, scim_app: Any) -> None:
    payload = json.loads(
        ok(
            runner.invoke(cli, ["-o", "json", "azure", "sp", "get", "incident", "--assignments"])
        ).stdout
    )

    assert payload["assignmentCount"] == 2
    names = [item["principalDisplayName"] for item in payload["appRoleAssignedTo"]]
    assert "AWS Platform Admins" in names


def test_an_unmatched_display_name_exits_4(runner: Any, cli: Any, scim_app: Any) -> None:
    result = failed(runner.invoke(cli, ["azure", "sp", "get", "no-such-app"]), 4)

    assert "no-such-app" in result.output


def test_ignore_missing_downgrades_a_miss_to_success(runner: Any, cli: Any, scim_app: Any) -> None:
    ok(runner.invoke(cli, ["azure", "sp", "get", "no-such-app", "--ignore-missing"]))


# ---------------------------------------------------------------------------
# assignments
# ---------------------------------------------------------------------------
def test_assignments_defaults_to_who_has_access(runner: Any, cli: Any, scim_app: Any) -> None:
    """appRoleAssignedTo, not appRoleAssignments: the question users actually ask."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "assignments", "incident"]))

    names = [json.loads(line)["principalDisplayName"] for line in lines(result.stdout)]
    assert names == ["AWS Platform Admins", "Ann Example"]


def test_outbound_inverts_the_direction(runner: Any, cli: Any, scim_app: Any) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "assignments", "incident", "--outbound"])
    )

    rows = [json.loads(line) for line in lines(result.stdout)]
    assert [row["principalType"] for row in rows] == ["ServicePrincipal"]


def test_the_role_guid_is_resolved_to_a_name(runner: Any, cli: Any, scim_app: Any) -> None:
    """An assignment carries appRoleId, which is unreadable without the app's roles."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "assignments", "incident"]))

    rows = [json.loads(line) for line in lines(result.stdout)]
    assert rows[0]["appRoleName"] == "User"


def test_the_all_zero_guid_becomes_default_access(runner: Any, cli: Any, scim_app: Any) -> None:
    """Graph's stand-in for an app that exposes no roles of its own."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "assignments", "incident"]))

    rows = [json.loads(line) for line in lines(result.stdout)]
    assert rows[1]["appRoleName"] == "Default Access"


def test_no_role_names_skips_the_extra_request(runner: Any, cli: Any, scim_app: Any) -> None:
    result = ok(
        runner.invoke(
            cli, ["-o", "ndjson", "azure", "sp", "assignments", "incident", "--no-role-names"]
        )
    )

    assert "appRoleName" not in json.loads(lines(result.stdout)[0])


def test_principal_filters_to_one_assignment(runner: Any, cli: Any, scim_app: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "assignments",
                "incident",
                "--principal",
                "AWS Platform Admins",
            ],
        )
    )

    rows = lines(result.stdout)
    assert len(rows) == 1
    assert json.loads(rows[0])["principalDisplayName"] == "AWS Platform Admins"


def test_principal_matching_is_case_insensitive(runner: Any, cli: Any, scim_app: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "assignments",
                "incident",
                "--principal",
                "aws platform admins",
            ],
        )
    )

    assert len(lines(result.stdout)) == 1


def test_principal_match_prefix_returns_every_match(runner: Any, cli: Any, scim_app: Any) -> None:
    """A prefix is for exploring: "who from the AWS estate has access to this app"."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "assignments",
                "incident",
                "--principal",
                "aws",
                "--principal-match",
                "prefix",
            ],
        )
    )

    names = [json.loads(line)["principalDisplayName"] for line in lines(result.stdout)]
    assert names == ["AWS Platform Admins"]


def test_principal_match_contains_finds_a_mid_string_match(
    runner: Any, cli: Any, scim_app: Any
) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "assignments",
                "incident",
                "--principal",
                "platform",
                "--principal-match",
                "contains",
            ],
        )
    )

    assert len(lines(result.stdout)) == 1


def test_a_prefix_that_matches_nothing_still_exits_4(runner: Any, cli: Any, scim_app: Any) -> None:
    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "assignments",
                "incident",
                "--principal",
                "gcp-",
                "--principal-match",
                "prefix",
            ],
        ),
        4,
    )

    assert "prefix" in result.output


def test_no_principal_returns_every_assignment(runner: Any, cli: Any, scim_app: Any) -> None:
    """The default: no filter, so both assignments come back."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "assignments", "incident"]))

    assert len(lines(result.stdout)) == 2


def test_a_principal_with_no_assignment_exits_4(runner: Any, cli: Any, scim_app: Any) -> None:
    """Scriptable: absence of an expected assignment is a failure, not an empty list."""
    result = failed(
        runner.invoke(cli, ["azure", "sp", "assignments", "incident", "--principal", "Nobody"]), 4
    )

    assert "Nobody" in result.output
