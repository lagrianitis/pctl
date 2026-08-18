"""End-to-end: `pctl azure raw`, the escape hatch onto any Graph path.

Worth its own module because `raw` is the one command with no schema of its own: it has
to pass a caller's parameters through untouched while still applying auth, retries and
pagination.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote_plus

import pytest

from helpers import GRAPH, failed, lines, ok

pytestmark = pytest.mark.e2e


def test_a_query_parameter_reaches_graph_unchanged(
    runner: Any, cli: Any, graph: Any, seen: list[str]
) -> None:
    import httpx

    def users(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"value": [{"id": "u1", "displayName": "Ann"}]})

    graph.get(f"{GRAPH}/users").mock(side_effect=users)

    result = ok(
        runner.invoke(
            cli,
            ["-o", "ndjson", "azure", "raw", "users", "--param", "$select=id,displayName"],
        )
    )

    assert json.loads(lines(result.stdout)[0])["id"] == "u1"
    assert "$select=id,displayName" in unquote_plus(seen[-1])


def test_a_malformed_param_is_a_usage_error(runner: Any, cli: Any, graph: Any) -> None:
    """`--param` without an `=` cannot become a query parameter, so reject it early."""
    failed(runner.invoke(cli, ["azure", "raw", "users", "--param", "broken"]), 2)
