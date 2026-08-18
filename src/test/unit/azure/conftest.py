"""Fixtures shared by the Azure unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from pctl.azure.graph import GraphClient
from pctl.config import AzureConfig


@pytest.fixture
def graph_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GraphClient:
    """A client that is never entered, so no connection pool is ever opened.

    The cache directory is redirected at a temp path because constructing the client
    builds a `TokenCache`, and a unit test must not read or write the developer's real
    token cache.
    """
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path))
    return GraphClient(AzureConfig.resolve(tenant_id="tid", client_id="cid"))
