"""Fixtures shared by the Azure smoke tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

CASE_PATH = ["azure"]
GROUPS_PATH = ["azure", "groups"]


@pytest.fixture
def azure(runner: Any, cli: Any) -> Callable[..., Any]:
    """Invoke `pctl azure ...` with the prog name real users see."""

    def invoke(*args: str) -> Any:
        return runner.invoke(cli, [*CASE_PATH, *args], prog_name="pctl")

    return invoke


@pytest.fixture
def groups(runner: Any, cli: Any) -> Callable[..., Any]:
    """Invoke `pctl azure groups ...`, the service most actions live under."""

    def invoke(*args: str) -> Any:
        return runner.invoke(cli, [*GROUPS_PATH, *args], prog_name="pctl")

    return invoke
