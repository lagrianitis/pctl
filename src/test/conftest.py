"""Fixtures shared by every tier.

Both fixtures import lazily, so collecting the unit tier costs nothing for tests that
never touch the CLI. Provider fakes deliberately do not live here: only the `e2e` tier
reaches a provider boundary, so its respx and moto setup belongs in `e2e/conftest.py`
and the per-case conftests beneath it.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def runner() -> Any:
    """A click test runner.

    Read data from `.stdout` and diagnostics from `.stderr`: click 8.2+ merges both
    into `.output`, and pctl writes summaries and warnings to stderr on purpose.
    """
    from click.testing import CliRunner

    return CliRunner()


@pytest.fixture
def cli() -> Any:
    """The root click group."""
    from pctl.cli import cli as root

    return root
