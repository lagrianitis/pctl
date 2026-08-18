"""End-to-end: `pctl azure groups`, against Graph faked with respx.

These are the checks the unit tier cannot make. `unit/azure/test_graph.py` proves the
transport builds a correct `$filter` in isolation; here the whole path runs, so a
command that builds the right filter but renders the wrong columns still fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, TENANT, failed, filters, graph_group, lines, ok

pytestmark = pytest.mark.e2e


def _paged(seen: list[str]) -> Any:
    """Two pages of groups, the first carrying an @odata.nextLink."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "skiptoken" in str(request.url):
            return httpx.Response(200, json={"value": [graph_group(3), graph_group(4)]})
        return httpx.Response(
            200,
            json={
                "value": [graph_group(0), graph_group(1), graph_group(2)],
                "@odata.nextLink": f"{GRAPH}/groups?$skiptoken=page2",
            },
        )

    return handler


# ---------------------------------------------------------------------------
# list: pagination and rendering
# ---------------------------------------------------------------------------
def test_pagination_follows_the_next_link(
    runner: Any, cli: Any, graph: Any, seen: list[str]
) -> None:
    """Five groups across two pages, in order, or the nextLink loop is broken."""
    graph.get(f"{GRAPH}/groups").mock(side_effect=_paged(seen))

    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "groups", "list"]))

    names = [json.loads(line)["displayName"] for line in lines(result.stdout)]
    assert names == [f"aws-team-{index}" for index in range(5)]


def test_the_page_size_asks_for_the_graph_maximum(
    runner: Any, cli: Any, graph: Any, seen: list[str]
) -> None:
    """$top=999 is what keeps a large tenant to a handful of round trips."""
    graph.get(f"{GRAPH}/groups").mock(side_effect=_paged(seen))

    ok(runner.invoke(cli, ["-o", "ndjson", "azure", "groups", "list"]))

    assert any("$top=999" in unquote_plus(url) for url in seen)


def test_limit_stops_early(runner: Any, cli: Any, graph: Any, seen: list[str]) -> None:
    graph.get(f"{GRAPH}/groups").mock(side_effect=_paged(seen))

    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "groups", "list", "-n", "2"]))

    assert len(lines(result.stdout)) == 2


def test_table_output_honours_columns(runner: Any, cli: Any, graph: Any, seen: list[str]) -> None:
    graph.get(f"{GRAPH}/groups").mock(side_effect=_paged(seen))

    result = ok(runner.invoke(cli, ["azure", "groups", "list", "-c", "displayName,id"]))

    assert lines(result.stdout)[0].split() == ["displayName", "id"]


def test_csv_writes_a_header_then_rows(runner: Any, cli: Any, graph: Any, seen: list[str]) -> None:
    graph.get(f"{GRAPH}/groups").mock(side_effect=_paged(seen))

    result = ok(
        runner.invoke(cli, ["-o", "csv", "azure", "groups", "list", "-c", "displayName,mail"])
    )

    assert lines(result.stdout)[:2] == ["displayName,mail", f"aws-team-0,team0@{TENANT}"]


def test_a_single_result_is_still_a_json_array(
    runner: Any, cli: Any, graph: Any, seen: list[str]
) -> None:
    """`list` returns a collection, so one item must not collapse to an object."""
    graph.get(f"{GRAPH}/groups").mock(side_effect=_paged(seen))

    result = ok(runner.invoke(cli, ["-o", "json", "azure", "groups", "list", "-n", "1"]))

    assert isinstance(json.loads(result.stdout), list)


# ---------------------------------------------------------------------------
# list: server-side filtering
# ---------------------------------------------------------------------------
def test_starts_with_escapes_single_quotes(
    runner: Any, cli: Any, graph: Any, seen: list[str]
) -> None:
    """An apostrophe in a group name must not break out of the OData literal."""
    import httpx

    def one_page(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"value": [graph_group(0)]})

    graph.get(f"{GRAPH}/groups").mock(side_effect=one_page)

    ok(runner.invoke(cli, ["azure", "groups", "list", "--starts-with", "o'brien-"]))

    assert filters(seen) == ["startswith(displayName,'o''brien-')"]


def test_search_sends_the_advanced_query_parameters(
    runner: Any, cli: Any, graph: Any, seen: list[str]
) -> None:
    """Graph full-text search only works with $count=true alongside it."""
    import httpx

    def one_page(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"value": [graph_group(0)]})

    graph.get(f"{GRAPH}/groups").mock(side_effect=one_page)

    ok(runner.invoke(cli, ["azure", "groups", "list", "--search", "platform"]))

    url = unquote_plus(seen[-1])
    assert '$search="displayName:platform"' in url
    assert "$count=true" in url


def test_count_only_prints_just_the_number(runner: Any, cli: Any, graph: Any) -> None:
    """Pipeable by design: no header, no label, one integer."""
    import httpx

    graph.get(f"{GRAPH}/groups").mock(
        return_value=httpx.Response(200, json={"@odata.count": 4211, "value": [graph_group(0)]})
    )

    result = ok(runner.invoke(cli, ["azure", "groups", "list", "--count-only"]))

    assert result.stdout.strip() == "4211"


# ---------------------------------------------------------------------------
# get: resolution by display name
# ---------------------------------------------------------------------------
@pytest.fixture
def named_groups(graph: Any, seen: list[str]) -> Any:
    """Graph routes resolving `Team A` and `Team B`, with relations attached.

    Relation routes are registered before the broader `/groups` route on purpose: respx
    matches in registration order, so the general route would otherwise shadow them.
    """
    import httpx

    graph.get(f"{GRAPH}/groups/a/members").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "u1", "displayName": "Ann"}]})
    )
    graph.get(f"{GRAPH}/groups/b/members").mock(
        return_value=httpx.Response(
            200, json={"value": [{"id": "u2", "displayName": "Bob"}, {"id": "u3"}]}
        )
    )
    graph.get(f"{GRAPH}/groups/a/owners").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "o1", "displayName": "Ola"}]})
    )
    graph.get(f"{GRAPH}/groups/a/members/$count").mock(return_value=httpx.Response(200, text="1"))
    graph.get(f"{GRAPH}/groups/a/owners/$count").mock(return_value=httpx.Response(200, text="1"))

    def by_display_name(request: httpx.Request) -> httpx.Response:
        url = unquote_plus(str(request.url))
        seen.append(str(request.url))
        if "'Team A'" in url:
            return httpx.Response(200, json={"value": [{"id": "a", "displayName": "Team A"}]})
        if "'Team B'" in url:
            return httpx.Response(200, json={"value": [{"id": "b", "displayName": "Team B"}]})
        return httpx.Response(200, json={"value": []})

    graph.get(f"{GRAPH}/groups").mock(side_effect=by_display_name)
    return graph


def test_a_single_group_is_an_object_not_an_array(runner: Any, cli: Any, named_groups: Any) -> None:
    """`get` of one name is a document, unlike `list`, so jq needs no [0]."""
    result = ok(runner.invoke(cli, ["-o", "json", "azure", "groups", "get", "Team A"]))

    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert payload["displayName"] == "Team A"


def test_exact_match_uses_a_display_name_equality_filter(
    runner: Any, cli: Any, named_groups: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["-o", "json", "azure", "groups", "get", "Team A"]))

    assert filters(seen) == ["displayName eq 'Team A'"]


def test_several_names_resolve_with_members_attached(
    runner: Any, cli: Any, named_groups: Any
) -> None:
    result = ok(
        runner.invoke(
            cli, ["-o", "json", "azure", "groups", "get", "Team A", "Team B", "--members"]
        )
    )

    payload = {group["displayName"]: group for group in json.loads(result.stdout)}
    assert [member["displayName"] for member in payload["Team A"]["members"]] == ["Ann"]
    assert payload["Team B"]["memberCount"] == 2


def test_counts_come_from_the_dedicated_count_endpoint(
    runner: Any, cli: Any, named_groups: Any
) -> None:
    """`--counts` must not page the whole membership just to length it."""
    result = ok(
        runner.invoke(
            cli, ["-o", "json", "azure", "groups", "get", "Team A", "--owners", "--counts"]
        )
    )

    payload = json.loads(result.stdout)
    assert payload["memberCount"] == 1
    assert payload["ownerCount"] == 1


def test_from_file_skips_comments_and_removes_duplicates(
    runner: Any, cli: Any, named_groups: Any, tmp_path: Path
) -> None:
    listing = tmp_path / "groups.txt"
    listing.write_text("# platform groups\nTeam A\n\nTeam A\n", encoding="utf-8")

    result = ok(runner.invoke(cli, ["-o", "json", "azure", "groups", "get", "-f", str(listing)]))

    assert isinstance(json.loads(result.stdout), dict)


def test_an_unmatched_display_name_exits_4(runner: Any, cli: Any, named_groups: Any) -> None:
    result = failed(runner.invoke(cli, ["azure", "groups", "get", "Nope"]), 4)

    assert "Nope" in result.output


def test_ignore_missing_downgrades_a_miss_to_success(
    runner: Any, cli: Any, named_groups: Any
) -> None:
    ok(runner.invoke(cli, ["azure", "groups", "get", "Nope", "--ignore-missing"]))


def test_no_names_at_all_is_a_usage_error(runner: Any, cli: Any, named_groups: Any) -> None:
    failed(runner.invoke(cli, ["azure", "groups", "get"]), 2)


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------
@pytest.fixture
def member_routes(graph: Any) -> Any:
    """Graph routes for `Team A`'s direct members, transitive members and owners."""
    import httpx

    member = {"id": "u1", "displayName": "Ann", "userPrincipalName": f"ann@{TENANT}"}
    graph.get(f"{GRAPH}/groups/a/transitiveMembers").mock(
        return_value=httpx.Response(200, json={"value": [member]})
    )
    graph.get(f"{GRAPH}/groups/a/owners").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "o1", "displayName": "Ola"}]})
    )
    graph.get(f"{GRAPH}/groups/a/members").mock(
        return_value=httpx.Response(200, json={"value": [member]})
    )
    graph.get(f"{GRAPH}/groups").mock(
        return_value=httpx.Response(200, json={"value": [{"id": "a", "displayName": "Team A"}]})
    )
    return graph


def test_members_csv_uses_the_default_member_columns(
    runner: Any, cli: Any, member_routes: Any
) -> None:
    result = ok(runner.invoke(cli, ["-o", "csv", "azure", "groups", "members", "Team A"]))

    assert lines(result.stdout)[:2] == [
        "displayName,userPrincipalName,id",
        f"Ann,ann@{TENANT},u1",
    ]


def test_the_alias_and_command_prefixes_resolve(runner: Any, cli: Any, member_routes: Any) -> None:
    """`az gr mem` is `azure groups members`, and it has to work end to end."""
    result = ok(runner.invoke(cli, ["-o", "csv", "az", "gr", "mem", "Team A", "--transitive"]))

    assert f"Ann,ann@{TENANT},u1" in result.stdout


def test_owners_are_returned_instead_of_members(runner: Any, cli: Any, member_routes: Any) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "ndjson", "azure", "groups", "members", "Team A", "--owners"])
    )

    assert json.loads(lines(result.stdout)[0])["id"] == "o1"
