"""End-to-end: `pctl azure sp owners`, `add-owner` and `remove-owner`.

These are the first writes in the CLI, so the assertions are about what reaches Graph
and when nothing does. Idempotency is the property that matters: re-running must not
produce a second owner, and must not fail.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from helpers import GRAPH, failed, lines, ok

pytestmark = pytest.mark.e2e

SP_ID = "sp-0001"
SCIM_APP = "Company Incident.io SCIM"
ANN_ID = "e6901838-637f-4bc7-b843-a8a7725a4872"
BOB_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def owned_app(graph: Any, seen: list[str]) -> Any:
    """An Enterprise Application owned by Ann, with Bob resolvable but not an owner."""
    import httpx

    graph.get(f"{GRAPH}/servicePrincipals/{SP_ID}/owners").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": ANN_ID,
                        "displayName": "Ann Example",
                        "userPrincipalName": "ann@example.com",
                    }
                ]
            },
        )
    )

    def users(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = str(request.url)
        if "Ann" in url:
            return httpx.Response(
                200, json={"value": [{"id": ANN_ID, "displayName": "Ann Example"}]}
            )
        if "Bob" in url:
            return httpx.Response(
                200, json={"value": [{"id": BOB_ID, "displayName": "Bob Example"}]}
            )
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/users").mock(side_effect=users)
    graph.get(f"{GRAPH}/servicePrincipals").mock(
        return_value=httpx.Response(
            200, json={"value": [{"id": SP_ID, "displayName": SCIM_APP, "appId": "app-1"}]}
        )
    )
    return graph


@pytest.fixture
def add_route(owned_app: Any) -> Any:
    """The owner reference POST, named so the test can count calls."""
    import httpx

    owned_app.post(f"{GRAPH}/servicePrincipals/{SP_ID}/owners/$ref", name="add").mock(
        return_value=httpx.Response(204)
    )
    return owned_app


@pytest.fixture
def remove_route(owned_app: Any) -> Any:
    """The owner reference DELETE, named so the test can count calls."""
    import httpx

    owned_app.delete(f"{GRAPH}/servicePrincipals/{SP_ID}/owners/{ANN_ID}/$ref", name="remove").mock(
        return_value=httpx.Response(204)
    )
    return owned_app


# ---------------------------------------------------------------------------
# owners
# ---------------------------------------------------------------------------
def test_owners_lists_the_current_owners(runner: Any, cli: Any, owned_app: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "owners", "incident"]))

    assert json.loads(lines(result.stdout)[0])["displayName"] == "Ann Example"


# ---------------------------------------------------------------------------
# add-owner
# ---------------------------------------------------------------------------
def test_adding_a_new_owner_posts_the_reference(runner: Any, cli: Any, add_route: Any) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "json", "azure", "sp", "add-owner", "incident", "Bob Example"])
    )

    assert add_route["add"].call_count == 1
    assert json.loads(result.stdout)["status"] == "added"


def test_the_posted_body_is_a_directory_object_reference(
    runner: Any, cli: Any, add_route: Any
) -> None:
    """Graph wants an @odata.id pointing at /directoryObjects/{id}, not a bare id."""
    ok(runner.invoke(cli, ["azure", "sp", "add-owner", "incident", "Bob Example"]))

    body = json.loads(add_route["add"].calls[0].request.content)
    assert body == {"@odata.id": f"{GRAPH}/directoryObjects/{BOB_ID}"}


def test_an_existing_owner_is_reported_without_writing(
    runner: Any, cli: Any, add_route: Any
) -> None:
    """The point of the feature: safe to re-run, exit 0, no duplicate owner."""
    result = ok(
        runner.invoke(cli, ["-o", "json", "azure", "sp", "add-owner", "incident", "Ann Example"])
    )

    assert add_route["add"].call_count == 0
    assert json.loads(result.stdout)["status"] == "already-owner"


def test_an_existing_owner_says_so_on_stderr(runner: Any, cli: Any, add_route: Any) -> None:
    result = ok(runner.invoke(cli, ["azure", "sp", "add-owner", "incident", "Ann Example"]))

    assert "already an owner" in result.stderr


def test_an_owner_can_be_given_as_an_object_id(runner: Any, cli: Any, add_route: Any) -> None:
    """A GUID skips resolution entirely, so no lookup request is made for it."""
    result = ok(runner.invoke(cli, ["-o", "json", "azure", "sp", "add-owner", "incident", BOB_ID]))

    assert json.loads(result.stdout)["ownerId"] == BOB_ID
    assert add_route["add"].call_count == 1


def test_an_unresolvable_owner_exits_4_without_writing(
    runner: Any, cli: Any, add_route: Any
) -> None:
    result = failed(runner.invoke(cli, ["azure", "sp", "add-owner", "incident", "Nobody"]), 4)

    assert add_route["add"].call_count == 0
    assert "groups are not searched" in result.output


# ---------------------------------------------------------------------------
# remove-owner
# ---------------------------------------------------------------------------
def test_removing_an_owner_deletes_the_reference(runner: Any, cli: Any, remove_route: Any) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "json", "azure", "sp", "remove-owner", "incident", "Ann Example"])
    )

    assert remove_route["remove"].call_count == 1
    assert json.loads(result.stdout)["status"] == "removed"


def test_the_delete_targets_the_ref_not_the_object(
    runner: Any, cli: Any, remove_route: Any
) -> None:
    """Without /$ref Graph deletes the user itself, which is the worst possible bug."""
    ok(runner.invoke(cli, ["azure", "sp", "remove-owner", "incident", "Ann Example"]))

    assert str(remove_route["remove"].calls[0].request.url).endswith("/$ref")


def test_removing_a_non_owner_is_reported_without_writing(
    runner: Any, cli: Any, remove_route: Any
) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "json", "azure", "sp", "remove-owner", "incident", "Bob Example"])
    )

    assert remove_route["remove"].call_count == 0
    assert json.loads(result.stdout)["status"] == "not-an-owner"


def test_removing_a_non_owner_says_so_on_stderr(runner: Any, cli: Any, remove_route: Any) -> None:
    result = ok(runner.invoke(cli, ["azure", "sp", "remove-owner", "incident", "Bob Example"]))

    assert "not an owner" in result.stderr


def test_dropping_below_two_owners_warns(runner: Any, cli: Any, remove_route: Any) -> None:
    """Microsoft's guidance is at least two owners, so removing the last one is loud."""
    result = ok(runner.invoke(cli, ["azure", "sp", "remove-owner", "incident", "Ann Example"]))

    assert "recommends at least 2" in result.stderr
