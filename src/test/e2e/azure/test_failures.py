"""End-to-end: how `pctl azure` fails.

The exit codes are a published contract, and the messages are the only thing standing
between a user and a support request. Both are asserted against the real command path,
because an error raised correctly in the transport can still be swallowed above it.
"""

from __future__ import annotations

from typing import Any

import pytest

from helpers import GRAPH, failed, graph_group, lines, ok

pytestmark = pytest.mark.e2e


def test_throttling_is_retried_transparently(
    runner: Any, cli: Any, graph: Any, no_sleep: None
) -> None:
    """A 429 with Retry-After is the transport's problem, not the user's."""
    import httpx

    graph.get(f"{GRAPH}/groups").mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"error": {"code": "TooManyRequests", "message": "slow down"}},
            ),
            httpx.Response(200, json={"value": [graph_group(0)]}),
        ]
    )

    result = ok(runner.invoke(cli, ["-o", "ndjson", "azure", "groups", "list"]))

    assert len(lines(result.stdout)) == 1


def test_a_bad_client_secret_exits_3(runner: Any, cli: Any, graph: Any) -> None:
    """Exit 3 is auth, and the AADSTS code is what makes the cause findable."""
    import httpx

    # Re-mock the fixture's named route rather than registering a second one for the
    # same URL: respx matches in registration order, so a new route would sit behind
    # the 200 the fixture already installed and never be reached.
    graph["token"].mock(
        return_value=httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "error_description": "AADSTS7000215: Invalid client secret provided.",
            },
        )
    )

    # --no-token-cache, otherwise a token cached by an earlier command in the same test
    # would be reused and the token endpoint never reached.
    result = failed(runner.invoke(cli, ["azure", "groups", "list", "--no-token-cache"]), 3)

    assert "AADSTS7000215" in result.output


def test_a_missing_graph_permission_exits_5(runner: Any, cli: Any, graph: Any) -> None:
    """Exit 5 is upstream: the request was well formed, Graph refused it."""
    import httpx

    graph.get(f"{GRAPH}/groups").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "Authorization_RequestDenied",
                    "message": "Insufficient privileges",
                }
            },
        )
    )

    result = failed(runner.invoke(cli, ["azure", "groups", "list"]), 5)

    assert "Insufficient privileges" in result.output


def test_a_missing_tenant_exits_2_and_names_the_variable(
    runner: Any, cli: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 2 is configuration, and the message has to say what to set."""
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("PCTL_TENANT_ID", raising=False)

    result = failed(runner.invoke(cli, ["azure", "groups", "list"]), 2)

    assert "AZURE_TENANT_ID" in result.output
