"""Fixtures for the Microsoft Graph end-to-end tests.

Every test here needs the same two things: an environment that looks like a configured
tenant, and a respx router with the token endpoint already answered. Neither is
interesting to the assertions, so both are fixtures.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers import CLIENT_ID, FAKE_JWT, FAKE_SECRET, TENANT, TOKEN_URL


@pytest.fixture(autouse=True)
def azure_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A configured tenant plus a private token cache, yielding the cache directory.

    Autouse because a command that falls back to the developer's real environment
    would either reach a live tenant or fail for the wrong reason. The `PCTL_*`
    overrides are cleared rather than set, so a developer's shell cannot redirect the
    authority or Graph base URL out from under the respx routes.
    """
    cache = tmp_path / "cache"
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", FAKE_SECRET)
    monkeypatch.setenv("PCTL_CACHE_DIR", str(cache))
    for name in (
        "PCTL_AZURE_SECRET_ID",
        "PCTL_NO_TOKEN_CACHE",
        "PCTL_GRAPH_SCOPE",
        "PCTL_AUTHORITY",
        "PCTL_GRAPH_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return cache


@pytest.fixture
def graph() -> Iterator[Any]:
    """A respx router with the token endpoint answered, named `token`.

    Look the route up as `graph["token"]` to assert on `call_count`, which is how the
    token cache tests tell a cache hit from a fresh authentication.

    `assert_all_called=False`: most tests register more routes than a single command
    needs, since the same fixture serves several commands.
    """
    import httpx
    import respx

    with respx.mock(assert_all_called=False) as router:
        router.post(TOKEN_URL, name="token").mock(
            return_value=httpx.Response(200, json={"access_token": FAKE_JWT, "expires_in": 3600})
        )
        yield router
