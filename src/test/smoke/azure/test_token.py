"""Smoke tier: the `pctl azure token` and `pctl azure raw` surface.

Both are case-level actions with no service of their own. Only help text and argument
parsing are covered; acquiring a token needs a tenant and belongs to the end-to-end
scripts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------------------
# token
# ---------------------------------------------------------------------------
def test_token_help_documents_masking(azure: Callable[..., Any]) -> None:
    """The masked default is a security property, so it must be documented."""
    stdout = ok(azure("token", "--help")).stdout
    assert "--raw" in stdout
    assert "masked" in stdout


def test_token_help_documents_cache_control(azure: Callable[..., Any]) -> None:
    stdout = ok(azure("token", "--help")).stdout
    assert "--clear-cache" in stdout
    assert "--no-token-cache" in stdout


def test_token_help_warns_that_decode_does_not_verify(azure: Callable[..., Any]) -> None:
    assert "no signature check" in ok(azure("token", "--help")).stdout


def test_token_takes_no_positional_arguments(azure: Callable[..., Any]) -> None:
    failed(azure("token", "unexpected"), 2)


# ---------------------------------------------------------------------------
# raw
# ---------------------------------------------------------------------------
def test_raw_requires_a_path(azure: Callable[..., Any]) -> None:
    failed(azure("raw"), 2)


def test_raw_rejects_a_malformed_param(azure: Callable[..., Any]) -> None:
    """Rejected during parsing, before any token is requested."""
    result = failed(azure("raw", "users", "--param", "broken"), 2)
    assert "KEY=VALUE" in result.output


def test_raw_help_documents_pagination_control(azure: Callable[..., Any]) -> None:
    assert "--no-paginate" in ok(azure("raw", "--help")).stdout
