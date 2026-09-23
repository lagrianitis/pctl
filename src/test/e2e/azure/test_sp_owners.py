"""End-to-end: `pctl azure sp owners`, `add-owner` and `remove-owner`.

These are the first writes in the CLI, so the assertions are about what reaches Graph
and when nothing does. Idempotency is the property that matters: re-running must not
produce a second owner, and must not fail.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, lines, ok

pytestmark = pytest.mark.e2e

SP_ID = "sp-0001"
SCIM_APP = "Company Incident.io SCIM"
ANN_ID = "e6901838-637f-4bc7-b843-a8a7725a4872"
BOB_ID = "11111111-2222-3333-4444-555555555555"
CAROL_ID = "22222222-3333-4444-5555-666666666666"


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
        url = unquote_plus(str(request.url))
        # Ann is findable by name, by UPN and by a mail that differs from the UPN. Bob is
        # findable by name only, so a test can prove the email path is distinct.
        if "Ann" in url or "ann@example.com" in url or "ann@example.onmicrosoft.com" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": ANN_ID,
                            "displayName": "Ann Example",
                            "userPrincipalName": "ann@example.onmicrosoft.com",
                            "mail": "ann@example.com",
                        }
                    ]
                },
            )
        if "Bob" in url or "bob@example.com" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": BOB_ID,
                            "displayName": "Bob Example",
                            "userPrincipalName": "bob@example.com",
                            "mail": "bob@example.com",
                        }
                    ]
                },
            )
        if "Carol" in url or "carol@example.com" in url:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": CAROL_ID,
                            "displayName": "Carol Example",
                            "userPrincipalName": "carol@example.com",
                            "mail": "carol@example.com",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/users").mock(side_effect=users)

    def principals(request: httpx.Request) -> httpx.Response:
        """Only answer for the app under test.

        This used to return the application for every query, which made owner resolution
        succeed for any name: `resolve_owner` tries users and then service principals, so
        "Nobody" came back as the application itself. The tests asserting that an
        unresolvable owner exits 4 without writing could not pass until this route said no.
        """
        url = unquote_plus(str(request.url))
        if "incident" in url.casefold() or SCIM_APP in url:
            return httpx.Response(
                200,
                json={"value": [{"id": SP_ID, "displayName": SCIM_APP, "appId": "app-1"}]},
            )
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/servicePrincipals").mock(side_effect=principals)
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
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "sp", "owners", "--app", "incident"]))

    assert json.loads(lines(result.stdout)[0])["displayName"] == "Ann Example"


# ---------------------------------------------------------------------------
# add-owner
# ---------------------------------------------------------------------------
def test_adding_a_new_owner_posts_the_reference(runner: Any, cli: Any, add_route: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
            ],
        )
    )

    assert add_route["add"].call_count == 1
    assert json.loads(lines(result.stdout)[0])["status"] == "added"


def test_several_owners_are_added_in_one_call(runner: Any, cli: Any, add_route: Any) -> None:
    """Two repeated --owner values, one request each, one read of the current owners."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
                "--owner",
                "Carol Example",
            ],
        )
    )

    assert add_route["add"].call_count == 2
    assert {json.loads(line)["status"] for line in lines(result.stdout)} == {"added"}


def test_emails_takes_a_comma_separated_list(runner: Any, cli: Any, add_route: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--emails",
                "bob@example.com,carol@example.com",
            ],
        )
    )

    assert add_route["add"].call_count == 2
    assert len(lines(result.stdout)) == 2


def test_owner_flags_and_emails_combine(runner: Any, cli: Any, add_route: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
                "--emails",
                "carol@example.com",
            ],
        )
    )

    assert len(lines(result.stdout)) == 2


def test_a_duplicate_owner_argument_is_collapsed(runner: Any, cli: Any, add_route: Any) -> None:
    """Naming the same person twice must not produce two rows or two writes."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "bob@example.com",
                "--emails",
                "bob@example.com",
            ],
        )
    )

    assert add_route["add"].call_count == 1
    assert len(lines(result.stdout)) == 1


def test_a_mixed_batch_reports_per_owner_status(runner: Any, cli: Any, add_route: Any) -> None:
    """Ann is already an owner, Bob is not: one write, two rows, exit 0."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Ann Example",
                "--owner",
                "Bob Example",
            ],
        )
    )

    statuses = {
        json.loads(line)["owner"]: json.loads(line)["status"] for line in lines(result.stdout)
    }
    assert statuses == {"Ann Example": "already-owner", "Bob Example": "added"}
    assert add_route["add"].call_count == 1


def test_one_unresolvable_owner_does_not_block_the_others(
    runner: Any, cli: Any, add_route: Any
) -> None:
    """Bob is still added, and the exit code still reports the failure."""
    result = failed(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
                "--owner",
                "Nobody",
            ],
        ),
        4,
    )

    assert add_route["add"].call_count == 1
    assert "Could not resolve 'Nobody'" in result.stderr


def test_ignore_missing_tolerates_an_unresolvable_owner(
    runner: Any, cli: Any, add_route: Any
) -> None:
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
                "--owner",
                "Nobody",
                "--ignore-missing",
            ],
        )
    )

    assert add_route["add"].call_count == 1


def test_no_owner_at_all_is_a_usage_error(runner: Any, cli: Any, add_route: Any) -> None:
    failed(runner.invoke(cli, ["azure", "sp", "add-owner", "--app", "incident"]), 2)


def test_the_posted_body_is_a_directory_object_reference(
    runner: Any, cli: Any, add_route: Any
) -> None:
    """Graph wants an @odata.id pointing at /directoryObjects/{id}, not a bare id."""
    ok(
        runner.invoke(
            cli,
            ["azure", "sp", "add-owner", "--app", "incident", "--owner", "Bob Example"],
        )
    )

    body = json.loads(add_route["add"].calls[0].request.content)
    assert body == {"@odata.id": f"{GRAPH}/directoryObjects/{BOB_ID}"}


def test_an_existing_owner_is_reported_without_writing(
    runner: Any, cli: Any, add_route: Any
) -> None:
    """The point of the feature: safe to re-run, exit 0, no duplicate owner."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                "Ann Example",
            ],
        )
    )

    assert add_route["add"].call_count == 0
    assert json.loads(lines(result.stdout)[0])["status"] == "already-owner"


def test_an_existing_owner_says_so_on_stderr(runner: Any, cli: Any, add_route: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            ["azure", "sp", "add-owner", "--app", "incident", "--owner", "Ann Example"],
        )
    )

    assert "already an owner" in result.stderr


def test_an_owner_can_be_given_as_an_object_id(runner: Any, cli: Any, add_route: Any) -> None:
    """A GUID skips resolution entirely, so no lookup request is made for it."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "add-owner",
                "--app",
                "incident",
                "--owner",
                BOB_ID,
            ],
        )
    )

    assert json.loads(lines(result.stdout)[0])["ownerId"] == BOB_ID
    assert add_route["add"].call_count == 1


def test_an_unresolvable_owner_exits_4_without_writing(
    runner: Any, cli: Any, add_route: Any
) -> None:
    result = failed(
        runner.invoke(cli, ["azure", "sp", "add-owner", "--app", "incident", "--owner", "Nobody"]),
        4,
    )

    assert add_route["add"].call_count == 0
    assert "groups are not searched" in result.output


# ---------------------------------------------------------------------------
# remove-owner
# ---------------------------------------------------------------------------
def test_removing_an_owner_deletes_the_reference(runner: Any, cli: Any, remove_route: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "remove-owner",
                "--app",
                "incident",
                "--owner",
                "Ann Example",
            ],
        )
    )

    assert remove_route["remove"].call_count == 1
    assert json.loads(lines(result.stdout)[0])["status"] == "removed"


def test_remove_owner_accepts_several_addresses(runner: Any, cli: Any, remove_route: Any) -> None:
    """Only Ann is an owner, so Bob reports not-an-owner and the run still succeeds."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "remove-owner",
                "--app",
                "incident",
                "--emails",
                "ann@example.com,bob@example.com",
            ],
        )
    )

    statuses = {
        json.loads(line)["owner"]: json.loads(line)["status"] for line in lines(result.stdout)
    }
    assert statuses == {"Ann Example": "removed", "Bob Example": "not-an-owner"}
    assert remove_route["remove"].call_count == 1


def test_the_delete_targets_the_ref_not_the_object(
    runner: Any, cli: Any, remove_route: Any
) -> None:
    """Without /$ref Graph deletes the user itself, which is the worst possible bug."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "remove-owner",
                "--app",
                "incident",
                "--owner",
                "Ann Example",
            ],
        )
    )

    assert str(remove_route["remove"].calls[0].request.url).endswith("/$ref")


def test_removing_a_non_owner_is_reported_without_writing(
    runner: Any, cli: Any, remove_route: Any
) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "remove-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
            ],
        )
    )

    assert remove_route["remove"].call_count == 0
    assert json.loads(lines(result.stdout)[0])["status"] == "not-an-owner"


def test_removing_a_non_owner_says_so_on_stderr(runner: Any, cli: Any, remove_route: Any) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "remove-owner",
                "--app",
                "incident",
                "--owner",
                "Bob Example",
            ],
        )
    )

    assert "not an owner" in result.stderr


def test_dropping_below_two_owners_warns(runner: Any, cli: Any, remove_route: Any) -> None:
    """Microsoft's guidance is at least two owners, so removing the last one is loud."""
    result = ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "remove-owner",
                "--app",
                "incident",
                "--owner",
                "Ann Example",
            ],
        )
    )

    assert "recommends at least 2" in result.stderr
