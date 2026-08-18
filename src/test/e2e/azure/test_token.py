"""End-to-end: `pctl azure token` and the on-disk token cache.

The cache is the difference between a 150-400ms round trip per invocation and none, so
the tests that matter most here count token requests rather than inspect output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from helpers import FAKE_JWT, FAKE_SECRET, GRAPH, ok

pytestmark = pytest.mark.e2e


@pytest.fixture
def empty_groups(graph: Any) -> Any:
    """An empty `/groups` response, for commands run only to trigger authentication."""
    import httpx

    graph.get(f"{GRAPH}/groups").mock(return_value=httpx.Response(200, json={"value": []}))
    return graph


def test_the_token_is_masked_by_default(runner: Any, cli: Any, graph: Any) -> None:
    """A bearer token in a terminal ends up in scrollback and CI logs."""
    result = ok(runner.invoke(cli, ["-o", "json", "azure", "token"]))

    record = json.loads(result.stdout)
    assert FAKE_SECRET not in result.stdout
    assert FAKE_JWT not in record["accessToken"]
    assert "…" in record["accessToken"]


def test_the_expiry_is_reported(runner: Any, cli: Any, graph: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "json", "azure", "token"]))

    assert json.loads(result.stdout)["expiresInSeconds"] > 3000


def test_raw_prints_the_bare_token(runner: Any, cli: Any, graph: Any) -> None:
    """`--raw` exists to be substituted into an Authorization header, nothing else."""
    result = ok(runner.invoke(cli, ["azure", "token", "--raw"]))

    assert result.stdout.strip() == FAKE_JWT


def test_decode_shows_the_jwt_claims(runner: Any, cli: Any, graph: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "json", "azure", "token", "--decode"]))

    assert json.loads(result.stdout)["claims"] == {"app": "pctl"}


def test_the_disk_cache_avoids_a_second_token_request(
    runner: Any, cli: Any, empty_groups: Any
) -> None:
    """Three commands, one authentication. This is the whole point of the cache."""
    for _ in range(3):
        ok(runner.invoke(cli, ["azure", "groups", "list"]))

    assert empty_groups["token"].call_count == 1


def test_the_cache_file_is_only_readable_by_its_owner(
    runner: Any, cli: Any, empty_groups: Any, azure_env: Path
) -> None:
    """0600 in a 0700 directory, or a shared machine leaks a live bearer token."""
    ok(runner.invoke(cli, ["azure", "groups", "list"]))

    cached = list(azure_env.glob("tokens/*.json"))
    assert len(cached) == 1
    assert cached[0].stat().st_mode & 0o777 == 0o600


def test_clear_cache_empties_the_directory(
    runner: Any, cli: Any, empty_groups: Any, azure_env: Path
) -> None:
    ok(runner.invoke(cli, ["azure", "groups", "list"]))
    assert list(azure_env.glob("tokens/*.json"))

    ok(runner.invoke(cli, ["azure", "token", "--clear-cache"]))

    assert not list(azure_env.glob("tokens/*.json"))


def test_no_token_cache_reauthenticates_every_run(runner: Any, cli: Any, empty_groups: Any) -> None:
    for _ in range(2):
        ok(runner.invoke(cli, ["azure", "groups", "list", "--no-token-cache"]))

    assert empty_groups["token"].call_count == 2
