"""Smoke tier: the `pctl oauth` surface and `pctl oauth token`.

Only help text, aliases and argument parsing are covered. Fetching a token needs a
provider, and belongs to the end-to-end tier. Every case below fails during
configuration, before anything could be sent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from helpers import failed, ok

pytestmark = pytest.mark.smoke


def flat(text: str) -> str:
    """Help with its wrapping undone, so a phrase is found wherever click broke the line."""
    return " ".join(text.split())


SETTINGS = [
    ("--issuer", "OAUTH_ISSUER"),
    ("--token-url", "OAUTH_TOKEN_URL"),
    ("--client-id", "OAUTH_CLIENT_ID"),
    ("--client-secret", "OAUTH_CLIENT_SECRET"),
    ("--audience", "OAUTH_AUDIENCE"),
    ("--scope", "OAUTH_SCOPE"),
    ("--secret-id", "PCTL_OAUTH_SECRET_ID"),
    ("--secret-region", "PCTL_SECRET_REGION"),
    ("--no-token-cache", "PCTL_NO_TOKEN_CACHE"),
]


@pytest.mark.parametrize(("flag", "variable"), SETTINGS)
def test_every_setting_is_a_flag_with_its_variable(
    oauth: Callable[..., Any], flag: str, variable: str
) -> None:
    """The contract: anything settable by variable is settable by flag, and says so."""
    stdout = ok(oauth("token", "--help")).stdout

    assert flag in stdout
    assert variable in stdout


def test_the_secret_flag_warns_about_shell_history(oauth: Callable[..., Any]) -> None:
    """Accepting the secret as a flag is deliberate, but nobody should do it blind."""
    stdout = flat(ok(oauth("token", "--help")).stdout)

    assert "shell history" in stdout


def test_token_help_documents_masking(oauth: Callable[..., Any]) -> None:
    stdout = flat(ok(oauth("token", "--help")).stdout)

    assert "--raw" in stdout
    assert "masked" in stdout


def test_token_help_warns_that_decode_does_not_verify(oauth: Callable[..., Any]) -> None:
    assert "no signature check" in flat(ok(oauth("token", "--help")).stdout)


@pytest.mark.parametrize("alias", ["auth", "auth0"])
def test_the_aliases_reach_the_case(runner: Any, cli: Any, alias: str) -> None:
    stdout = flat(ok(runner.invoke(cli, [alias, "token", "--help"], prog_name="pctl")).stdout)

    assert "client credentials" in stdout


def test_the_root_help_shows_the_aliases(runner: Any, cli: Any) -> None:
    stdout = ok(runner.invoke(cli, ["--help"], prog_name="pctl")).stdout

    assert "oauth (auth, auth0)" in stdout


def test_token_takes_no_positional_arguments(oauth: Callable[..., Any]) -> None:
    failed(oauth("token", "unexpected"), 2)


def test_a_missing_client_id_is_a_usage_error(oauth: Callable[..., Any]) -> None:
    result = failed(oauth("token", "--token-url", "https://idp.example.test/oauth/token"), 2)

    assert "OAUTH_CLIENT_ID" in result.output


def test_a_missing_provider_is_a_usage_error(oauth: Callable[..., Any]) -> None:
    result = failed(oauth("token", "--client-id", "client"), 2)

    assert "OAUTH_ISSUER" in result.output


def test_a_missing_secret_is_a_usage_error(oauth: Callable[..., Any]) -> None:
    result = failed(
        oauth(
            "token",
            "--token-url",
            "https://idp.example.test/oauth/token",
            "--client-id",
            "client",
        ),
        2,
    )

    assert "OAUTH_CLIENT_SECRET" in result.output
