"""End-to-end: `pctl azure users get`, against Graph faked with respx.

The behaviour worth pinning is the form detection: an object ID goes straight to
`/users/{id}`, an address is filtered on userPrincipalName *and* mail because those
differ, and a display name goes through `$filter`. Each takes a different route, so each
is asserted on the request that actually left.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, filters, lines, ok

pytestmark = pytest.mark.e2e

ANN_ID = "e6901838-637f-4bc7-b843-a8a7725a4872"
BOB_ID = "11111111-2222-3333-4444-555555555555"

ANN = {
    "id": ANN_ID,
    "displayName": "Ann Example",
    "userPrincipalName": "ann@example.onmicrosoft.com",
    "mail": "ann@example.com",
    "jobTitle": "Platform Engineer",
    "department": "Platform",
    "accountEnabled": True,
}
BOB = {
    "id": BOB_ID,
    "displayName": "Bob Example",
    "userPrincipalName": "bob@example.com",
    "mail": "bob@example.com",
}


@pytest.fixture
def directory(graph: Any, seen: list[str]) -> Any:
    """Graph routes for a two-person directory.

    The collection route is registered after the by-id route so respx matches the more
    specific path first.
    """
    import httpx

    graph.get(f"{GRAPH}/users/{ANN_ID}").mock(return_value=httpx.Response(200, json=ANN))

    def collection(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url))
        if "ann@example.com" in url or "ann@example.onmicrosoft.com" in url or "Ann" in url:
            return httpx.Response(200, json={"value": [ANN]})
        if "bob@example.com" in url or "Bob" in url:
            return httpx.Response(200, json={"value": [BOB]})
        if "Example" in url:
            # A prefix or search match that hits both people, so ambiguity is reachable.
            return httpx.Response(200, json={"value": [ANN, BOB]})
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/users").mock(side_effect=collection)
    return graph


# ---------------------------------------------------------------------------
# the three identifier forms
# ---------------------------------------------------------------------------
def test_an_address_returns_the_user_object(runner: Any, cli: Any, directory: Any) -> None:
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "users", "get", "ann@example.com"])).stdout
    )

    assert payload["id"] == ANN_ID
    assert payload["displayName"] == "Ann Example"
    assert payload["jobTitle"] == "Platform Engineer"


def test_an_address_is_matched_against_upn_and_mail(
    runner: Any, cli: Any, directory: Any, seen: list[str]
) -> None:
    """The two differ in practice, so checking only one would miss half the cases."""
    ok(runner.invoke(cli, ["azure", "users", "get", "ann@example.com"]))

    assert filters(seen) == ["userPrincipalName eq 'ann@example.com' or mail eq 'ann@example.com'"]


def test_a_upn_that_differs_from_mail_also_resolves(runner: Any, cli: Any, directory: Any) -> None:
    payload = json.loads(
        ok(
            runner.invoke(
                cli, ["-o", "json", "azure", "users", "get", "ann@example.onmicrosoft.com"]
            )
        ).stdout
    )

    assert payload["id"] == ANN_ID


def test_a_display_name_uses_an_equality_filter(
    runner: Any, cli: Any, directory: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "users", "get", "Ann Example"]))

    assert filters(seen) == ["displayName eq 'Ann Example'"]


def test_an_object_id_skips_the_collection_entirely(
    runner: Any, cli: Any, directory: Any, seen: list[str]
) -> None:
    """A GUID addresses /users/{id} directly, so no filtered query is sent."""
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "users", "get", ANN_ID])).stdout
    )

    assert payload["id"] == ANN_ID
    assert seen == []


# ---------------------------------------------------------------------------
# rendering and selection
# ---------------------------------------------------------------------------
def test_one_user_is_an_object_not_an_array(runner: Any, cli: Any, directory: Any) -> None:
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "users", "get", "ann@example.com"])).stdout
    )

    assert isinstance(payload, dict)


def test_several_identifiers_resolve_concurrently(runner: Any, cli: Any, directory: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            ["-o", "ndjson", "azure", "users", "get", "ann@example.com", "bob@example.com"],
        )
    )

    ids = [json.loads(line)["id"] for line in lines(result.stdout)]
    assert sorted(ids) == sorted([ANN_ID, BOB_ID])


def test_select_narrows_the_requested_fields(
    runner: Any, cli: Any, directory: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "users", "get", "ann@example.com", "--select", "id,mail"]))

    assert "$select=id,mail" in unquote_plus(seen[-1])


def test_csv_uses_the_default_columns(runner: Any, cli: Any, directory: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "csv", "azure", "users", "get", "ann@example.com"]))

    assert lines(result.stdout)[0] == "displayName,userPrincipalName,mail,id"


# ---------------------------------------------------------------------------
# failure modes
# ---------------------------------------------------------------------------
def test_an_unknown_address_exits_4(runner: Any, cli: Any, directory: Any) -> None:
    result = failed(runner.invoke(cli, ["azure", "users", "get", "nobody@example.com"]), 4)

    assert "nobody@example.com" in result.output


def test_an_ambiguous_display_name_is_refused(runner: Any, cli: Any, directory: Any) -> None:
    """Two people can share a name, and the caller is about to act on the answer."""
    result = failed(
        runner.invoke(cli, ["azure", "users", "get", "Example", "--match", "prefix"]), 2
    )

    assert "2 users match" in result.output


def test_one_bad_identifier_does_not_block_the_others(
    runner: Any, cli: Any, directory: Any
) -> None:
    result = failed(
        runner.invoke(
            cli,
            ["-o", "ndjson", "azure", "users", "get", "ann@example.com", "nobody@example.com"],
        ),
        4,
    )

    assert len(lines(result.stdout)) == 1


def test_ignore_missing_tolerates_an_unknown_identifier(
    runner: Any, cli: Any, directory: Any
) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "users",
                "get",
                "ann@example.com",
                "nobody@example.com",
                "--ignore-missing",
            ],
        )
    )

    assert len(lines(result.stdout)) == 1
