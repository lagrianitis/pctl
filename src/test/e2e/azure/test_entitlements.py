"""End-to-end: `pctl azure eam`, against Graph faked with respx.

These collections have a narrower OData surface than the directory, and the assertions
reflect that: the request must not carry `$count` or `ConsistencyLevel`, `--contains` must
filter locally rather than sending an operator Graph rejects, and the path must be nested
under identityGovernance.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, filters, lines, ok

pytestmark = pytest.mark.e2e

EAM = f"{GRAPH}/identityGovernance/entitlementManagement"
PACKAGE_ID = "a914b616-e04e-476b-aa37-91038f0b165b"
CATALOG_ID = "d4f2d1b6-0a08-4987-9efd-fd8baae9e842"

PACKAGES = [
    {"id": PACKAGE_ID, "displayName": "AWS Platform Access", "isHidden": False},
    {"id": "p2", "displayName": "AWS Billing Access", "isHidden": False},
    {"id": "p3", "displayName": "Incident Response", "isHidden": True},
]
CATALOGS = [
    {
        "id": CATALOG_ID,
        "displayName": "AWS Platform",
        "catalogType": "userManaged",
        "state": "published",
    },
    {"id": "c2", "displayName": "Corporate", "catalogType": "serviceDefault", "state": "published"},
]


@pytest.fixture
def governance(graph: Any, seen: list[str]) -> Any:
    """Routes for the access package and catalog collections."""
    import httpx

    def packages(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url))
        if "displayName eq 'AWS Platform Access'" in url:
            return httpx.Response(200, json={"value": [PACKAGES[0]]})
        if "startswith(displayName,'AWS " in url:
            return httpx.Response(200, json={"value": PACKAGES[:2]})
        return httpx.Response(200, json={"value": PACKAGES})

    def catalogs(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url))
        if "displayName eq 'AWS Platform'" in url:
            return httpx.Response(200, json={"value": [CATALOGS[0]]})
        return httpx.Response(200, json={"value": CATALOGS})

    graph.get(f"{EAM}/accessPackages/{PACKAGE_ID}").mock(
        return_value=httpx.Response(200, json=PACKAGES[0])
    )
    graph.get(f"{EAM}/catalogs/{CATALOG_ID}").mock(
        return_value=httpx.Response(200, json=CATALOGS[0])
    )
    graph.get(f"{EAM}/accessPackages").mock(side_effect=packages)
    graph.get(f"{EAM}/catalogs").mock(side_effect=catalogs)
    return graph


# ---------------------------------------------------------------------------
# the narrower OData surface
# ---------------------------------------------------------------------------
def test_the_request_carries_no_count_parameter(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    """$count is not supported here, and sending it makes Graph reject the request."""
    ok(runner.invoke(cli, ["azure", "eam", "list-packages"]))

    assert "$count" not in unquote_plus(seen[-1])


def test_the_request_carries_no_consistency_level_header(
    runner: Any, cli: Any, governance: Any
) -> None:
    """The advanced-query header belongs to directory collections, not this one."""
    ok(runner.invoke(cli, ["azure", "eam", "list-packages"]))

    request = governance.calls[-1].request
    assert "ConsistencyLevel" not in request.headers


def test_the_path_is_nested_under_identity_governance(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "eam", "list-packages"]))

    assert "/identityGovernance/entitlementManagement/accessPackages" in seen[-1]


# ---------------------------------------------------------------------------
# list-packages
# ---------------------------------------------------------------------------
def test_list_packages_streams_the_collection(runner: Any, cli: Any, governance: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-packages"]))

    assert len(lines(result.stdout)) == 3


def test_starts_with_is_pushed_to_graph(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    result = ok(
        runner.invoke(
            cli, ["-o", "ndjson", "azure", "eam", "list-packages", "--starts-with", "AWS "]
        )
    )

    assert filters(seen) == ["startswith(displayName,'AWS ')"]
    assert len(lines(result.stdout)) == 2


def test_name_becomes_an_equality_filter(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "eam", "list-packages", "--name", "AWS Platform Access"]))

    assert filters(seen) == ["displayName eq 'AWS Platform Access'"]


def test_contains_filters_locally_and_sends_no_filter(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    """Graph has no substring operator here, so the narrowing happens after fetching."""
    result = ok(
        runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-packages", "--contains", "aws"])
    )

    assert filters(seen) == []
    names = [json.loads(line)["displayName"] for line in lines(result.stdout)]
    assert names == ["AWS Platform Access", "AWS Billing Access"]


def test_contains_is_case_insensitive(runner: Any, cli: Any, governance: Any) -> None:
    result = ok(
        runner.invoke(
            cli, ["-o", "ndjson", "azure", "eam", "list-packages", "--contains", "INCIDENT"]
        )
    )

    assert len(lines(result.stdout)) == 1


def test_a_limit_applies_after_local_filtering(runner: Any, cli: Any, governance: Any) -> None:
    """Capping before the filter would cap the wrong set and drop real matches."""
    result = ok(
        runner.invoke(
            cli,
            ["-o", "ndjson", "azure", "eam", "list-packages", "--contains", "aws", "-n", "1"],
        )
    )

    assert len(lines(result.stdout)) == 1


def test_a_raw_filter_is_passed_through_untouched(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "eam", "list-packages", "--filter", "isHidden eq false"]))

    assert filters(seen) == ["isHidden eq false"]


def test_the_default_columns_are_package_shaped(runner: Any, cli: Any, governance: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "csv", "azure", "eam", "list-packages"]))

    assert lines(result.stdout)[0] == "displayName,isHidden,id"


# ---------------------------------------------------------------------------
# get-package
# ---------------------------------------------------------------------------
def test_get_package_by_name(runner: Any, cli: Any, governance: Any) -> None:
    payload = json.loads(
        ok(
            runner.invoke(cli, ["-o", "json", "azure", "eam", "get-package", "AWS Platform Access"])
        ).stdout
    )

    assert payload["id"] == PACKAGE_ID


def test_get_package_by_id_addresses_it_directly(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "eam", "get-package", PACKAGE_ID])).stdout
    )

    assert payload["displayName"] == "AWS Platform Access"
    assert seen == []


def test_get_package_by_id_still_returns_exactly_one(
    runner: Any, cli: Any, governance: Any
) -> None:
    """An ID is not a pattern, so it can only ever match one thing."""
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "eam", "get-package", PACKAGE_ID])).stdout
    )

    assert isinstance(payload, dict)


def test_with_policies_expands_the_policies(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    ok(
        runner.invoke(
            cli, ["azure", "eam", "get-package", "AWS Platform Access", "--with-policies"]
        )
    )

    assert "$expand=assignmentPolicies" in unquote_plus(seen[-1])


def test_a_contains_pattern_returns_every_match(runner: Any, cli: Any, governance: Any) -> None:
    """A pattern matching several packages is the normal case, not an error."""
    result = ok(
        runner.invoke(
            cli, ["-o", "ndjson", "azure", "eam", "get-package", "AWS", "--match", "contains"]
        )
    )

    names = [json.loads(line)["displayName"] for line in lines(result.stdout)]
    assert names == ["AWS Platform Access", "AWS Billing Access"]


def test_a_prefix_pattern_returns_every_match(runner: Any, cli: Any, governance: Any) -> None:
    result = ok(
        runner.invoke(
            cli, ["-o", "ndjson", "azure", "eam", "get-package", "AWS ", "--match", "prefix"]
        )
    )

    assert len(lines(result.stdout)) == 2


def test_several_matches_render_as_an_array(runner: Any, cli: Any, governance: Any) -> None:
    payload = json.loads(
        ok(
            runner.invoke(
                cli, ["-o", "json", "azure", "eam", "get-package", "AWS", "--match", "contains"]
            )
        ).stdout
    )

    assert isinstance(payload, list)
    assert len(payload) == 2


def test_a_single_match_renders_as_an_object(runner: Any, cli: Any, governance: Any) -> None:
    """So jq needs no index for the common case, matching `groups get`."""
    payload = json.loads(
        ok(
            runner.invoke(
                cli,
                ["-o", "json", "azure", "eam", "get-package", "Incident", "--match", "contains"],
            )
        ).stdout
    )

    assert isinstance(payload, dict)
    assert payload["id"] == "p3"


def test_an_unknown_package_exits_4(runner: Any, cli: Any, governance: Any) -> None:
    result = failed(
        runner.invoke(cli, ["azure", "eam", "get-package", "nope", "--match", "contains"]), 4
    )

    assert "nope" in result.output


def test_the_not_found_message_suggests_the_pattern_modes(
    runner: Any, cli: Any, governance: Any
) -> None:
    """Exact is the default, and the pattern modes are what usually rescue it."""
    result = failed(runner.invoke(cli, ["azure", "eam", "get-package", "Platform"]), 4)

    assert "--match prefix" in result.output
    assert "--match contains" in result.output


# ---------------------------------------------------------------------------
# catalogs
# ---------------------------------------------------------------------------
def test_list_catalogs_streams_the_collection(runner: Any, cli: Any, governance: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-catalogs"]))

    assert len(lines(result.stdout)) == 2


def test_the_catalog_columns_differ_from_the_package_ones(
    runner: Any, cli: Any, governance: Any
) -> None:
    result = ok(runner.invoke(cli, ["-o", "csv", "azure", "eam", "list-catalogs"]))

    assert lines(result.stdout)[0] == "displayName,catalogType,state,id"


def test_get_catalog_by_name(runner: Any, cli: Any, governance: Any) -> None:
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "eam", "get-catalog", "AWS Platform"])).stdout
    )

    assert payload["id"] == CATALOG_ID


def test_get_catalog_by_id(runner: Any, cli: Any, governance: Any) -> None:
    payload = json.loads(
        ok(runner.invoke(cli, ["-o", "json", "azure", "eam", "get-catalog", CATALOG_ID])).stdout
    )

    assert payload["displayName"] == "AWS Platform"


# ---------------------------------------------------------------------------
# --catalog: scoping packages to a catalog by name
# ---------------------------------------------------------------------------
def test_catalog_name_is_resolved_then_used_as_a_filter(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    """The name is looked up first, because the filter needs the catalog's id."""
    ok(runner.invoke(cli, ["azure", "eam", "list-packages", "--catalog", "AWS Platform"]))

    assert "displayName eq 'AWS Platform'" in filters(seen)
    assert f"catalog/id eq '{CATALOG_ID}'" in filters(seen)


def test_a_catalog_id_skips_the_lookup(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "eam", "list-packages", "--catalog", CATALOG_ID]))

    assert filters(seen) == [f"catalog/id eq '{CATALOG_ID}'"]


def test_catalog_scope_combines_with_a_name_filter(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "eam",
                "list-packages",
                "--catalog",
                CATALOG_ID,
                "--starts-with",
                "AWS ",
            ],
        )
    )

    assert f"startswith(displayName,'AWS ') and catalog/id eq '{CATALOG_ID}'" in filters(seen)


def test_a_raw_filter_wins_over_the_catalog_shortcut(
    runner: Any, cli: Any, governance: Any, seen: list[str]
) -> None:
    """Someone who wrote OData by hand means it, so the shortcut stays out of the way."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "eam",
                "list-packages",
                "--catalog",
                CATALOG_ID,
                "--filter",
                "isHidden eq true",
            ],
        )
    )

    assert filters(seen) == ["isHidden eq true"]


def test_an_unknown_catalog_exits_4(runner: Any, cli: Any, governance: Any) -> None:
    result = failed(
        runner.invoke(cli, ["azure", "eam", "list-packages", "--catalog", "no-such-catalog"]), 4
    )

    assert "no-such-catalog" in result.output


# ---------------------------------------------------------------------------
# list-assignments
# ---------------------------------------------------------------------------
ASSIGNMENTS = [
    {
        "id": "asg1",
        "state": "Delivered",
        "target": {"objectId": "u1", "displayName": "Ann Example", "email": "ann@example.com"},
        "accessPackage": {"id": PACKAGE_ID, "displayName": "AWS Platform Access"},
    },
    {
        "id": "asg2",
        "state": "Delivered",
        "target": {"objectId": "u2", "displayName": "Bob Example", "email": "bob@example.com"},
        "accessPackage": {"id": PACKAGE_ID, "displayName": "AWS Platform Access"},
    },
    {
        "id": "asg3",
        "state": "Expired",
        "target": {"objectId": "u3", "displayName": "Carol Example", "email": "carol@example.com"},
        "accessPackage": {"id": PACKAGE_ID, "displayName": "AWS Platform Access"},
    },
]


@pytest.fixture
def assignments(governance: Any, seen: list[str]) -> Any:
    """The assignments collection, filtered by whatever $filter arrives."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = unquote_plus(str(request.url))
        items = ASSIGNMENTS
        if "state eq 'Delivered'" in url:
            items = [item for item in items if item["state"] == "Delivered"]
        elif "state eq 'Expired'" in url:
            items = [item for item in items if item["state"] == "Expired"]
        return httpx.Response(200, json={"value": items})

    governance.get(f"{EAM}/assignments").mock(side_effect=handler)
    return governance


def test_the_package_name_becomes_an_access_package_filter(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    """The name is resolved first, because the filter needs the package's id."""
    ok(
        runner.invoke(
            cli,
            ["azure", "eam", "list-assignments", "--access-package", "AWS Platform Access"],
        )
    )

    assert f"accessPackage/id eq '{PACKAGE_ID}'" in filters(seen)


def test_package_and_state_combine_into_one_filter(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    """This is the request the feature was specified against."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "eam",
                "list-assignments",
                "--access-package",
                PACKAGE_ID,
                "--state",
                "Delivered",
            ],
        )
    )

    assert f"accessPackage/id eq '{PACKAGE_ID}' and state eq 'Delivered'" in filters(seen)


def test_a_package_id_skips_the_lookup(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "eam", "list-assignments", "--access-package", PACKAGE_ID]))

    assert filters(seen) == [f"accessPackage/id eq '{PACKAGE_ID}'"]


def test_the_state_filter_narrows_server_side(runner: Any, cli: Any, assignments: Any) -> None:
    result = ok(
        runner.invoke(
            cli, ["-o", "ndjson", "azure", "eam", "list-assignments", "--state", "Delivered"]
        )
    )

    states = {json.loads(line)["state"] for line in lines(result.stdout)}
    assert states == {"Delivered"}
    assert len(lines(result.stdout)) == 2


def test_target_and_package_are_expanded_by_default(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    """Without the expansion an assignment is two GUIDs and a state."""
    ok(runner.invoke(cli, ["azure", "eam", "list-assignments"]))

    assert "$expand=target,accessPackage" in unquote_plus(seen[-1])


def test_no_expand_drops_the_expansion(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    ok(runner.invoke(cli, ["azure", "eam", "list-assignments", "--no-expand"]))

    assert "$expand" not in unquote_plus(seen[-1])


def test_the_nested_names_are_lifted_to_the_top_level(
    runner: Any, cli: Any, assignments: Any
) -> None:
    """A table column cannot address target.displayName, so it is copied up."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-assignments"]))

    first = json.loads(lines(result.stdout)[0])
    assert first["targetDisplayName"] == "Ann Example"
    assert first["targetEmail"] == "ann@example.com"
    assert first["accessPackageName"] == "AWS Platform Access"


def test_the_nested_objects_survive_flattening(runner: Any, cli: Any, assignments: Any) -> None:
    """The additions must not replace what json consumers already rely on."""
    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-assignments"]))

    first = json.loads(lines(result.stdout)[0])
    assert first["target"]["objectId"] == "u1"
    assert first["accessPackage"]["id"] == PACKAGE_ID


def test_the_default_columns_are_assignment_shaped(runner: Any, cli: Any, assignments: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "csv", "azure", "eam", "list-assignments"]))

    assert lines(result.stdout)[0] == "targetDisplayName,targetEmail,accessPackageName,state,id"


def test_target_filters_locally_on_name(runner: Any, cli: Any, assignments: Any) -> None:
    result = ok(
        runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-assignments", "--target", "Ann"])
    )

    assert len(lines(result.stdout)) == 1


def test_target_also_matches_an_email(runner: Any, cli: Any, assignments: Any) -> None:
    """A person is as likely to be looked up by address as by name."""
    result = ok(
        runner.invoke(cli, ["-o", "ndjson", "azure", "eam", "list-assignments", "--target", "bob@"])
    )

    assert json.loads(lines(result.stdout)[0])["targetDisplayName"] == "Bob Example"


def test_a_raw_filter_replaces_the_shortcuts(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "eam",
                "list-assignments",
                "--access-package",
                PACKAGE_ID,
                "--filter",
                "state eq 'Expired'",
            ],
        )
    )

    assert filters(seen) == ["state eq 'Expired'"]


def test_an_invalid_state_is_rejected_before_any_request(
    runner: Any, cli: Any, assignments: Any, seen: list[str]
) -> None:
    """Graph's states are capitalised exactly, so a typo must fail at parse time."""
    failed(runner.invoke(cli, ["azure", "eam", "list-assignments", "--state", "delivered"]), 2)

    assert seen == []
