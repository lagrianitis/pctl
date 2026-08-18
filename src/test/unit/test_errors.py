"""Unit tests for `pctl.errors`.

The exit codes are a published contract that CI jobs branch on, so they are pinned
here by number rather than by referencing the constants they come from. If someone
renumbers them, this test is the thing that objects.
"""

from __future__ import annotations

import click
import pytest

from pctl.errors import (
    AuthError,
    ConfigError,
    NotFoundError,
    PctlError,
    UpstreamError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [
        (PctlError, 1),
        (ConfigError, 2),
        (AuthError, 3),
        (NotFoundError, 4),
        (UpstreamError, 5),
    ],
)
def test_exit_codes_are_stable(error: type[PctlError], exit_code: int) -> None:
    assert error("boom").exit_code == exit_code


@pytest.mark.parametrize("error", [PctlError, ConfigError, AuthError, NotFoundError, UpstreamError])
def test_every_error_is_a_click_exception(error: type[PctlError]) -> None:
    """click prints these itself and honours `exit_code`; nothing calls sys.exit."""
    assert issubclass(error, click.ClickException)


def test_the_message_survives_to_the_output() -> None:
    assert NotFoundError("no group matched").format_message() == "no group matched"


def test_errors_are_distinguishable_by_type() -> None:
    """Callers catch specific tiers, so the hierarchy must stay flat under PctlError."""
    assert not issubclass(AuthError, NotFoundError)
    assert issubclass(AuthError, PctlError)
