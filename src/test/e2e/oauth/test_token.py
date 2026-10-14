"""End-to-end: `pctl oauth token`, the client credentials grant.

The provider is faked with respx, so these assert on what a command actually sent and
what it did with the answer: the form fields, the precedence between a flag and its
variable, the cache, and the exit code for each way the provider can say no.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from helpers import (
    FAKE_JWT,
    FAKE_SECRET,
    OAUTH_AUDIENCE,
    OAUTH_CLIENT_ID,
    OAUTH_DISCOVERY_URL,
    OAUTH_ISSUER,
    OAUTH_TOKEN_URL,
    failed,
    ok,
)

pytestmark = pytest.mark.e2e

CREDENTIALS = ["--client-id", OAUTH_CLIENT_ID, "--client-secret", FAKE_SECRET]
BASE = ["--token-url", OAUTH_TOKEN_URL, *CREDENTIALS]


def token(runner: Any, cli: Any, *args: str) -> Any:
    return runner.invoke(cli, ["oauth", "token", *args])


def reply(status: int = 200, **kwargs: Any) -> Any:
    """A fake provider response. httpx is imported here to keep collection cheap."""
    import httpx

    return httpx.Response(status, **kwargs)


def unreachable() -> Any:
    """The error httpx raises when the provider cannot be connected to."""
    import httpx

    return httpx.ConnectError("no route")


# ---------------------------------------------------------------------------
# what is shown
# ---------------------------------------------------------------------------
def test_the_token_is_masked_by_default(runner: Any, cli: Any, provider: Any) -> None:
    """A bearer token in a terminal ends up in scrollback and CI logs."""
    result = ok(runner.invoke(cli, ["-o", "json", "oauth", "token", *BASE]))

    record = json.loads(result.stdout)
    assert FAKE_JWT not in result.stdout
    assert "…" in record["accessToken"]


def test_the_record_describes_the_request(runner: Any, cli: Any, provider: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "json", "oauth", "token", *BASE]))

    record = json.loads(result.stdout)
    assert record["flow"] == "client_credentials"
    assert record["clientId"] == OAUTH_CLIENT_ID
    assert record["expiresInSeconds"] > 3000


def test_the_secret_is_never_echoed(runner: Any, cli: Any, provider: Any) -> None:
    result = ok(runner.invoke(cli, ["-v", "-o", "json", "oauth", "token", *BASE]))

    assert FAKE_SECRET not in result.output


def test_raw_prints_the_bare_token(runner: Any, cli: Any, provider: Any) -> None:
    """`--raw` exists to be substituted into an Authorization header, nothing else."""
    result = ok(token(runner, cli, *BASE, "--raw"))

    assert result.stdout.strip() == FAKE_JWT


def test_decode_shows_the_jwt_claims(runner: Any, cli: Any, provider: Any) -> None:
    result = ok(runner.invoke(cli, ["-o", "json", "oauth", "token", *BASE, "--decode"]))

    assert json.loads(result.stdout)["claims"] == {"app": "pctl"}


# ---------------------------------------------------------------------------
# what is sent
# ---------------------------------------------------------------------------
def test_the_request_is_a_form_with_the_grant_type(
    runner: Any, cli: Any, provider: Any, sent: Callable[[Any], dict[str, str]]
) -> None:
    ok(token(runner, cli, *BASE))

    request = provider["token"].calls.last.request
    assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert sent(provider["token"]) == {
        "grant_type": "client_credentials",
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": FAKE_SECRET,
    }


def test_audience_and_scope_are_sent_when_given(
    runner: Any, cli: Any, provider: Any, sent: Callable[[Any], dict[str, str]]
) -> None:
    ok(token(runner, cli, *BASE, "--audience", OAUTH_AUDIENCE, "--scope", "read write"))

    fields = sent(provider["token"])
    assert fields["audience"] == OAUTH_AUDIENCE
    assert fields["scope"] == "read write"


def test_settings_given_as_variables_alone_are_enough(
    runner: Any,
    cli: Any,
    provider: Any,
    sent: Callable[[Any], dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_TOKEN_URL", OAUTH_TOKEN_URL)
    monkeypatch.setenv("OAUTH_CLIENT_ID", "from-env")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret-from-env")
    monkeypatch.setenv("OAUTH_AUDIENCE", OAUTH_AUDIENCE)

    ok(token(runner, cli))

    fields = sent(provider["token"])
    assert fields["client_id"] == "from-env"
    assert fields["client_secret"] == "secret-from-env"
    assert fields["audience"] == OAUTH_AUDIENCE


def test_a_flag_beats_its_variable(
    runner: Any,
    cli: Any,
    provider: Any,
    sent: Callable[[Any], dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each setting, in one request: the flag value must reach the wire."""
    monkeypatch.setenv("OAUTH_TOKEN_URL", "https://wrong.example.test/oauth/token")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "from-env")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "secret-from-env")
    monkeypatch.setenv("OAUTH_AUDIENCE", "https://wrong.example.test")
    monkeypatch.setenv("OAUTH_SCOPE", "wrong")

    ok(token(runner, cli, *BASE, "--audience", OAUTH_AUDIENCE, "--scope", "right"))

    assert sent(provider["token"]) == {
        "grant_type": "client_credentials",
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": FAKE_SECRET,
        "audience": OAUTH_AUDIENCE,
        "scope": "right",
    }


def test_the_alias_runs_the_same_command(runner: Any, cli: Any, provider: Any) -> None:
    for alias in ("auth", "auth0"):
        result = ok(runner.invoke(cli, [alias, "token", *BASE, "--raw"]))

        assert result.stdout.strip() == FAKE_JWT


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def discovery(provider: Any, **document: str) -> Any:
    return provider.get(OAUTH_DISCOVERY_URL).mock(
        return_value=reply(200, json={"token_endpoint": OAUTH_TOKEN_URL, **document})
    )


def test_the_endpoint_is_discovered_from_the_issuer(runner: Any, cli: Any, provider: Any) -> None:
    route = discovery(provider)

    result = ok(token(runner, cli, "--issuer", OAUTH_ISSUER, *CREDENTIALS, "--raw"))

    assert result.stdout.strip() == FAKE_JWT
    assert route.call_count == 1


def test_a_trailing_slash_on_the_issuer_is_tolerated(runner: Any, cli: Any, provider: Any) -> None:
    """Auth0 publishes its issuer with one, and the document path must not double up."""
    route = discovery(provider)

    ok(token(runner, cli, "--issuer", f"{OAUTH_ISSUER}/", *CREDENTIALS))

    assert route.call_count == 1


def test_naming_the_token_url_skips_discovery(runner: Any, cli: Any, provider: Any) -> None:
    route = discovery(provider)

    ok(token(runner, cli, "--issuer", OAUTH_ISSUER, *BASE))

    assert route.call_count == 0


def test_a_broken_discovery_document_is_a_usage_error(runner: Any, cli: Any, provider: Any) -> None:
    provider.get(OAUTH_DISCOVERY_URL).mock(return_value=reply(404))

    result = failed(token(runner, cli, "--issuer", OAUTH_ISSUER, *CREDENTIALS), 2)

    assert "discovery" in result.output


def test_a_discovery_document_without_a_token_endpoint_is_a_usage_error(
    runner: Any, cli: Any, provider: Any
) -> None:
    provider.get(OAUTH_DISCOVERY_URL).mock(return_value=reply(200, json={}))

    result = failed(token(runner, cli, "--issuer", OAUTH_ISSUER, *CREDENTIALS), 2)

    assert "token endpoint" in result.output


# ---------------------------------------------------------------------------
# the cache
# ---------------------------------------------------------------------------
def test_the_disk_cache_avoids_a_second_request(runner: Any, cli: Any, provider: Any) -> None:
    """Three commands, one request. This is the whole point of the cache."""
    for _ in range(3):
        ok(token(runner, cli, *BASE))

    assert provider["token"].call_count == 1


def test_no_token_cache_asks_every_time(runner: Any, cli: Any, provider: Any) -> None:
    for _ in range(2):
        ok(token(runner, cli, *BASE, "--no-token-cache"))

    assert provider["token"].call_count == 2


def test_the_variable_turns_the_cache_off_too(
    runner: Any, cli: Any, provider: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCTL_NO_TOKEN_CACHE", "1")

    for _ in range(2):
        ok(token(runner, cli, *BASE))

    assert provider["token"].call_count == 2


def test_another_audience_does_not_reuse_the_token(runner: Any, cli: Any, provider: Any) -> None:
    """A token for one API must not answer a request for another."""
    ok(token(runner, cli, *BASE, "--audience", "https://one.example.test"))
    ok(token(runner, cli, *BASE, "--audience", "https://two.example.test"))

    assert provider["token"].call_count == 2


def test_the_cache_file_is_only_readable_by_its_owner(
    runner: Any, cli: Any, provider: Any, oauth_env: Path
) -> None:
    ok(token(runner, cli, *BASE))

    cached = list(oauth_env.glob("tokens/*.json"))
    assert len(cached) == 1
    assert cached[0].stat().st_mode & 0o777 == 0o600


def test_the_secret_is_not_written_to_the_cache(
    runner: Any, cli: Any, provider: Any, oauth_env: Path
) -> None:
    ok(token(runner, cli, *BASE))

    assert FAKE_SECRET not in next(oauth_env.glob("tokens/*.json")).read_text()


def test_a_token_with_no_lifetime_is_not_reused(runner: Any, cli: Any, provider: Any) -> None:
    provider["token"].mock(return_value=reply(200, json={"access_token": FAKE_JWT}))

    for _ in range(2):
        ok(token(runner, cli, *BASE))

    assert provider["token"].call_count == 2


# ---------------------------------------------------------------------------
# when the provider says no
# ---------------------------------------------------------------------------
def test_rejected_credentials_exit_3_with_the_providers_reason(
    runner: Any, cli: Any, provider: Any
) -> None:
    provider["token"].mock(
        return_value=reply(
            401, json={"error": "invalid_client", "error_description": "Unauthorized"}
        )
    )

    result = failed(token(runner, cli, *BASE), 3)

    assert "invalid_client" in result.output
    assert FAKE_SECRET not in result.output


def test_an_unreachable_provider_exits_3(runner: Any, cli: Any, provider: Any) -> None:
    provider["token"].mock(side_effect=unreachable())

    result = failed(token(runner, cli, *BASE), 3)

    assert "Could not reach" in result.output


def test_a_response_without_a_token_exits_3(runner: Any, cli: Any, provider: Any) -> None:
    provider["token"].mock(return_value=reply(200, json={"token_type": "Bearer"}))

    result = failed(token(runner, cli, *BASE), 3)

    assert "no access_token" in result.output


def test_a_response_that_is_not_json_exits_3(runner: Any, cli: Any, provider: Any) -> None:
    provider["token"].mock(return_value=reply(200, text="<html>"))

    failed(token(runner, cli, *BASE), 3)


def test_a_failure_is_not_cached(runner: Any, cli: Any, provider: Any) -> None:
    """A rejected request must not leave anything behind to be mistaken for a token."""
    provider["token"].mock(return_value=reply(401, json={"error": "invalid_client"}))
    failed(token(runner, cli, *BASE), 3)

    provider["token"].mock(return_value=reply(200, json={"access_token": FAKE_JWT}))
    ok(token(runner, cli, *BASE))

    assert provider["token"].call_count == 2


# ---------------------------------------------------------------------------
# configuration errors never reach the provider
# ---------------------------------------------------------------------------
def test_a_missing_secret_exits_2_without_a_request(runner: Any, cli: Any, provider: Any) -> None:
    failed(token(runner, cli, "--token-url", OAUTH_TOKEN_URL, "--client-id", OAUTH_CLIENT_ID), 2)

    assert provider["token"].call_count == 0
