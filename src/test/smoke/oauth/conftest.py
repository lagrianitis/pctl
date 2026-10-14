"""Fixtures shared by the OAuth smoke tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

CASE_PATH = ["oauth"]


@pytest.fixture
def oauth(runner: Any, cli: Any) -> Callable[..., Any]:
    """Invoke `pctl oauth ...` with the prog name real users see."""

    def invoke(*args: str) -> Any:
        return runner.invoke(cli, [*CASE_PATH, *args], prog_name="pctl")

    return invoke
