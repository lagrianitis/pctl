"""Unit tests for the pure parts of `pctl.azure.graph`.

No HTTP happens here. What is asserted is query construction (an unescaped quote in a
display name would otherwise break the filter, or worse, alter it), the advanced-query
headers Graph requires for `$search`, and error-message extraction, which is what the
user actually sees when Graph refuses a request.
"""

from __future__ import annotations

import httpx
import pytest

from pctl.azure.graph import (
    ADVANCED_QUERY_HEADERS,
    DEFAULT_GROUP_SELECT,
    GRAPH_MAX_PAGE_SIZE,
    GraphClient,
    _describe,
    escape_odata,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# OData escaping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Team A", "Team A"),
        ("O'Brien", "O''Brien"),
        ("''", "''''"),
        ("", ""),
    ],
)
def test_escape_odata_doubles_single_quotes(raw: str, expected: str) -> None:
    assert escape_odata(raw) == expected


def test_escaping_keeps_a_quoted_name_inside_its_literal() -> None:
    """The escaped name must not be able to close the literal early."""
    escaped = escape_odata("O'Brien")
    assert f"displayName eq '{escaped}'" == "displayName eq 'O''Brien'"


# ---------------------------------------------------------------------------
# query construction
# ---------------------------------------------------------------------------
def test_page_size_is_capped_at_the_graph_maximum(graph_client: GraphClient) -> None:
    params, _ = graph_client._list_params(
        select=None, filter_expr=None, search=None, order_by=None, page_size=5000, count=False
    )
    assert params["$top"] == GRAPH_MAX_PAGE_SIZE


def test_select_is_comma_joined(graph_client: GraphClient) -> None:
    params, _ = graph_client._list_params(
        select=DEFAULT_GROUP_SELECT,
        filter_expr=None,
        search=None,
        order_by=None,
        page_size=999,
        count=False,
    )
    assert params["$select"] == ",".join(DEFAULT_GROUP_SELECT)


def test_a_plain_filter_needs_no_special_headers(graph_client: GraphClient) -> None:
    params, headers = graph_client._list_params(
        select=None,
        filter_expr="displayName eq 'x'",
        search=None,
        order_by=None,
        page_size=999,
        count=False,
    )
    assert params["$filter"] == "displayName eq 'x'"
    assert headers == {}


def test_search_requests_the_advanced_query_api(graph_client: GraphClient) -> None:
    """`$search` only works with ConsistencyLevel: eventual and $count=true."""
    params, headers = graph_client._list_params(
        select=None, filter_expr=None, search="platform", order_by=None, page_size=999, count=False
    )
    assert params["$search"] == '"displayName:platform"'
    assert params["$count"] == "true"
    assert headers == ADVANCED_QUERY_HEADERS


def test_an_explicitly_quoted_search_is_passed_through(graph_client: GraphClient) -> None:
    params, _ = graph_client._list_params(
        select=None,
        filter_expr=None,
        search='"mail:aws"',
        order_by=None,
        page_size=999,
        count=False,
    )
    assert params["$search"] == '"mail:aws"'


def test_ordering_alongside_a_filter_needs_the_advanced_api(graph_client: GraphClient) -> None:
    _, headers = graph_client._list_params(
        select=None,
        filter_expr="startswith(displayName,'aws')",
        search=None,
        order_by="displayName",
        page_size=999,
        count=False,
    )
    assert headers == ADVANCED_QUERY_HEADERS


def test_ordering_alone_does_not(graph_client: GraphClient) -> None:
    params, headers = graph_client._list_params(
        select=None,
        filter_expr=None,
        search=None,
        order_by="displayName",
        page_size=999,
        count=False,
    )
    assert params["$orderby"] == "displayName"
    assert headers == {}


# ---------------------------------------------------------------------------
# error extraction
# ---------------------------------------------------------------------------
def test_describe_pulls_the_graph_error_message() -> None:
    response = httpx.Response(
        403,
        json={
            "error": {
                "code": "Authorization_RequestDenied",
                "message": "Insufficient privileges",
            }
        },
    )
    assert _describe(response) == "Insufficient privileges"


def test_describe_falls_back_to_the_graph_error_code() -> None:
    response = httpx.Response(400, json={"error": {"code": "BadRequest"}})
    assert _describe(response) == "BadRequest"


def test_describe_handles_the_entra_id_error_shape() -> None:
    """The token endpoint uses a flat error/error_description pair, not Graph's shape."""
    response = httpx.Response(
        401,
        json={
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided.\nTrace ID: x",
        },
    )
    assert _describe(response) == "AADSTS7000215: Invalid client secret provided."


def test_describe_handles_a_non_json_body() -> None:
    response = httpx.Response(502, text="<html>gateway</html>")
    assert _describe(response) == "<html>gateway</html>"


def test_describe_is_bounded() -> None:
    """Error text goes to the terminal, so it must not be unbounded."""
    response = httpx.Response(400, json={"error": {"message": "x" * 5000}})
    assert len(_describe(response)) <= 400


def test_describe_of_an_empty_body_uses_the_reason_phrase() -> None:
    assert _describe(httpx.Response(503, text="")) == httpx.Response(503).reason_phrase
