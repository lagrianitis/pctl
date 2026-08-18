"""Fixtures shared by the AWS smoke tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

SERVICE_PATH = ["aws", "ddb"]


@pytest.fixture
def ddb(runner: Any, cli: Any) -> Callable[..., Any]:
    """Invoke `pctl aws ddb ...` with the prog name real users see.

    Saves repeating the case and service on every call, and keeps usage lines in help
    output labelled `pctl` rather than `cli`.
    """

    def invoke(*args: str) -> Any:
        return runner.invoke(cli, [*SERVICE_PATH, *args], prog_name="pctl")

    return invoke
