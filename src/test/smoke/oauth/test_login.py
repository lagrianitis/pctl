"""Smoke tier: the `pctl oauth login` surface.

Only help text and argument parsing are covered. The flow itself needs a provider and a
browser, and belongs to the end-to-end tier. Every failure below happens during
configuration, before a browser could be opened.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke

LOGIN_SETTINGS = [
    ("--authorize-url", "OAUTH_AUTHORIZE_URL"),
    ("--redirect-uri", "OAUTH_REDIRECT_URI"),
    ("--login-timeout", "OAUTH_LOGIN_TIMEOUT"),
    ("--issuer", "OAUTH_ISSUER"),
    ("--token-url", "OAUTH_TOKEN_URL"),
    ("--client-id", "OAUTH_CLIENT_ID"),
    ("--client-secret", "OAUTH_CLIENT_SECRET"),
    ("--audience", "OAUTH_AUDIENCE"),
    ("--scope", "OAUTH_SCOPE"),
]


def flat(text: str) -> str:
    """Help with its wrapping undone, so a phrase is found wherever click broke the line."""
    return " ".join(text.split())


@pytest.mark.parametrize(("flag", "variable"), LOGIN_SETTINGS)
def test_every_setting_is_a_flag_with_its_variable(
    oauth: Callable[..., Any], flag: str, variable: str
) -> None:
    stdout = ok(oauth("login", "--help")).stdout

    assert flag in stdout
    assert variable in stdout


def test_login_has_no_cache_flag(oauth: Callable[..., Any]) -> None:
    """A user's token is never cached, so there is nothing for the flag to switch off."""
    assert "--no-token-cache" not in ok(oauth("login", "--help")).stdout


def test_login_help_explains_both_ways_back(oauth: Callable[..., Any]) -> None:
    stdout = flat(ok(oauth("login", "--help")).stdout)

    assert "loopback" in stdout
    assert "paste" in stdout


def test_login_help_says_nothing_is_written_to_disk(oauth: Callable[..., Any]) -> None:
    assert "Nothing is written to disk" in flat(ok(oauth("login", "--help")).stdout)


def test_login_help_documents_masking(oauth: Callable[..., Any]) -> None:
    stdout = flat(ok(oauth("login", "--help")).stdout)

    assert "--raw" in stdout
    assert "masked" in stdout


def test_login_takes_no_positional_arguments(oauth: Callable[..., Any]) -> None:
    failed(oauth("login", "unexpected"), 2)


def test_a_zero_timeout_is_rejected(oauth: Callable[..., Any]) -> None:
    failed(oauth("login", "--login-timeout", "0"), 2)


def test_a_missing_client_id_is_a_usage_error(oauth: Callable[..., Any]) -> None:
    result = failed(oauth("login", "--token-url", "https://idp.example.test/oauth/token"), 2)

    assert "OAUTH_CLIENT_ID" in result.output


def test_a_missing_redirect_is_a_usage_error(oauth: Callable[..., Any]) -> None:
    result = failed(
        oauth(
            "login",
            "--token-url",
            "https://idp.example.test/oauth/token",
            "--authorize-url",
            "https://idp.example.test/authorize",
            "--client-id",
            "client",
        ),
        2,
    )

    assert "OAUTH_REDIRECT_URI" in result.output
