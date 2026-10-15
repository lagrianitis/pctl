"""End-to-end: `pctl oauth login`, the browser login with PKCE.

A `user` fixture plays the person at the browser, so both ways a login can come back are
exercised for real: a redirect caught on a loopback port, and an address pasted at the
prompt. The provider is faked with respx, and the assertions are about what crossed the
boundary: what the login page was asked for, what the code exchange sent, and what was
refused.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from helpers import (
    FAKE_JWT,
    FAKE_SECRET,
    OAUTH_AUDIENCE,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_ISSUER,
    OAUTH_TOKEN_URL,
    failed,
    ok,
    reply,
)

pytestmark = pytest.mark.e2e

PROVIDER = ["--token-url", OAUTH_TOKEN_URL, "--authorize-url", OAUTH_AUTHORIZE_URL]
CLIENT = ["--client-id", OAUTH_CLIENT_ID]
PASTE_REDIRECT = "https://app.example.test/callback"


def login(runner: Any, cli: Any, *args: str, **kwargs: Any) -> Any:
    return runner.invoke(cli, ["oauth", "login", *args], **kwargs)


def loopback(port: int) -> str:
    return f"http://127.0.0.1:{port}/callback"


def challenge_of(verifier: str) -> str:
    """The S256 challenge a provider would compute from a verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# a redirect caught on a loopback port
# ---------------------------------------------------------------------------
def test_a_loopback_login_returns_the_token(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {}

    result = ok(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port), "--raw")
    )

    assert result.stdout.strip() == FAKE_JWT
    assert user.failures == []


def test_the_token_is_masked_by_default(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {}

    result = ok(
        login(runner, cli, "-o", "json", *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port))
    )

    record = json.loads(result.stdout)
    assert record["flow"] == "authorization_code"
    assert FAKE_JWT not in result.stdout
    assert "…" in record["accessToken"]


def test_the_login_page_is_asked_for_a_code_with_pkce(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {}

    ok(login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)))

    assert user.opened[0].startswith(f"{OAUTH_AUTHORIZE_URL}?")
    query = user.login_query
    assert query["response_type"] == "code"
    assert query["client_id"] == OAUTH_CLIENT_ID
    assert query["redirect_uri"] == loopback(free_port)
    assert query["code_challenge_method"] == "S256"
    assert query["scope"] == "openid profile email"
    assert "audience" not in query


def test_audience_and_scope_reach_the_login_page(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {}

    ok(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--redirect-uri",
            loopback(free_port),
            "--audience",
            OAUTH_AUDIENCE,
            "--scope",
            "openid read",
        )
    )

    assert user.login_query["audience"] == OAUTH_AUDIENCE
    assert user.login_query["scope"] == "openid read"


def test_the_code_exchange_proves_possession_of_the_verifier(
    runner: Any,
    cli: Any,
    provider: Any,
    user: Any,
    free_port: int,
    sent: Callable[[Any], dict[str, str]],
) -> None:
    """The verifier never went to the login page, only its hash did."""
    user.reply = {}

    ok(login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)))

    fields = sent(provider["token"])
    assert fields["grant_type"] == "authorization_code"
    assert fields["code"] == "auth-code"
    assert fields["client_id"] == OAUTH_CLIENT_ID
    assert fields["redirect_uri"] == loopback(free_port)
    assert challenge_of(fields["code_verifier"]) == user.login_query["code_challenge"]
    assert fields["code_verifier"] not in user.opened[0]


def test_a_public_client_sends_no_secret(
    runner: Any,
    cli: Any,
    provider: Any,
    user: Any,
    free_port: int,
    sent: Callable[[Any], dict[str, str]],
) -> None:
    user.reply = {}

    ok(login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)))

    assert "client_secret" not in sent(provider["token"])


def test_a_confidential_client_sends_its_secret(
    runner: Any,
    cli: Any,
    provider: Any,
    user: Any,
    free_port: int,
    sent: Callable[[Any], dict[str, str]],
) -> None:
    user.reply = {}

    ok(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--client-secret",
            FAKE_SECRET,
            "--redirect-uri",
            loopback(free_port),
        )
    )

    assert sent(provider["token"])["client_secret"] == FAKE_SECRET


def test_the_endpoints_follow_from_the_issuer(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    """The login page is <issuer>/authorize and the code goes to <issuer>/oauth/token."""
    user.reply = {}

    ok(
        login(
            runner,
            cli,
            "--issuer",
            OAUTH_ISSUER,
            *CLIENT,
            "--redirect-uri",
            loopback(free_port),
        )
    )

    assert user.opened[0].startswith(f"{OAUTH_AUTHORIZE_URL}?")
    assert provider["token"].call_count == 1


def test_an_authorize_url_beats_the_issuer(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {}

    ok(
        login(
            runner,
            cli,
            "--issuer",
            OAUTH_ISSUER,
            "--authorize-url",
            "https://other.example.test/login",
            *CLIENT,
            "--redirect-uri",
            loopback(free_port),
        )
    )

    assert user.opened[0].startswith("https://other.example.test/login?")


def test_a_flag_beats_the_redirect_variable(
    runner: Any,
    cli: Any,
    provider: Any,
    user: Any,
    free_port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://127.0.0.1:1/wrong")
    user.reply = {}

    ok(login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)))

    assert user.login_query["redirect_uri"] == loopback(free_port)


def test_the_variables_alone_are_enough(
    runner: Any,
    cli: Any,
    provider: Any,
    user: Any,
    free_port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_TOKEN_URL", OAUTH_TOKEN_URL)
    monkeypatch.setenv("OAUTH_AUTHORIZE_URL", OAUTH_AUTHORIZE_URL)
    monkeypatch.setenv("OAUTH_CLIENT_ID", OAUTH_CLIENT_ID)
    monkeypatch.setenv("OAUTH_REDIRECT_URI", loopback(free_port))
    user.reply = {}

    result = ok(login(runner, cli, "--raw"))

    assert result.stdout.strip() == FAKE_JWT


def test_a_login_never_writes_the_cache(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int, oauth_env: Path
) -> None:
    """A user's token is theirs. Nothing about it is kept once the command ends."""
    user.reply = {}

    ok(login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)))

    assert not list(oauth_env.glob("tokens/*.json"))


# ---------------------------------------------------------------------------
# a redirect that must be refused
# ---------------------------------------------------------------------------
def test_a_forged_state_is_refused_and_nothing_is_exchanged(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {"state": "forged"}

    result = failed(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)), 3
    )

    assert "State mismatch" in result.output
    assert provider["token"].call_count == 0


def test_a_redirect_with_no_state_is_refused(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {"state": None}

    result = failed(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)), 3
    )

    assert "no state" in result.output
    assert provider["token"].call_count == 0


def test_a_provider_error_is_reported_and_nothing_is_exchanged(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {"error": "access_denied", "error_description": "No thanks", "code": None}

    result = failed(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)), 3
    )

    assert "access_denied: No thanks" in result.output
    assert provider["token"].call_count == 0


def test_a_redirect_with_no_code_is_refused(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    user.reply = {"code": None}

    result = failed(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)), 3
    )

    assert "No authorization code" in result.output


def test_a_rejected_code_exits_3_with_the_providers_reason(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    provider["token"].mock(
        return_value=reply(400, json={"error": "invalid_grant", "error_description": "expired"})
    )
    user.reply = {}

    result = failed(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)), 3
    )

    assert "invalid_grant: expired" in result.output


def test_giving_up_waiting_exits_3(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    """Nobody comes back from the browser. The wait is bounded, and says so."""
    result = failed(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--redirect-uri",
            loopback(free_port),
            "--login-timeout",
            "0.2",
        ),
        3,
    )

    assert "No login redirect" in result.output
    assert len(user.opened) == 1


# ---------------------------------------------------------------------------
# configuration that cannot work
# ---------------------------------------------------------------------------
def test_a_missing_redirect_exits_2_before_the_browser_opens(
    runner: Any, cli: Any, provider: Any, user: Any
) -> None:
    result = failed(login(runner, cli, *PROVIDER, *CLIENT), 2)

    assert "OAUTH_REDIRECT_URI" in result.output
    assert user.opened == []


def test_a_loopback_redirect_needs_a_port(runner: Any, cli: Any, provider: Any, user: Any) -> None:
    result = failed(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", "http://127.0.0.1/callback"), 2
    )

    assert "explicit port" in result.output
    assert user.opened == []


def test_a_busy_port_exits_2(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", free_port))
        holder.listen()

        result = failed(
            login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", loopback(free_port)), 2
        )

    assert "Cannot listen" in result.output
    assert user.opened == []


def test_no_authorize_endpoint_exits_2_before_the_browser_opens(
    runner: Any, cli: Any, provider: Any, user: Any, free_port: int
) -> None:
    result = failed(
        login(
            runner,
            cli,
            "--token-url",
            OAUTH_TOKEN_URL,
            *CLIENT,
            "--redirect-uri",
            loopback(free_port),
        ),
        2,
    )

    assert "authorize endpoint" in result.output
    assert user.opened == []


# ---------------------------------------------------------------------------
# a redirect pasted back, for clients registered with a page pctl cannot listen on
# ---------------------------------------------------------------------------
def test_a_pasted_code_is_exchanged(
    runner: Any, cli: Any, provider: Any, user: Any, sent: Callable[[Any], dict[str, str]]
) -> None:
    result = ok(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--redirect-uri",
            PASTE_REDIRECT,
            "--raw",
            input="pasted-code\n",
        )
    )

    assert result.stdout.strip() == FAKE_JWT
    assert sent(provider["token"])["code"] == "pasted-code"
    assert sent(provider["token"])["redirect_uri"] == PASTE_REDIRECT


def test_a_pasted_address_is_read_for_its_code(
    runner: Any, cli: Any, provider: Any, user: Any, sent: Callable[[Any], dict[str, str]]
) -> None:
    ok(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--redirect-uri",
            PASTE_REDIRECT,
            input=f"{PASTE_REDIRECT}?code=from-address\n",
        )
    )

    assert sent(provider["token"])["code"] == "from-address"


def test_the_login_page_is_printed_in_case_no_browser_opens(
    runner: Any, cli: Any, provider: Any, user: Any
) -> None:
    result = ok(
        login(runner, cli, *PROVIDER, *CLIENT, "--redirect-uri", PASTE_REDIRECT, input="code\n")
    )

    assert user.opened[0] in result.stderr
    assert "paste the full address" in result.stderr


def test_a_pasted_address_with_the_wrong_state_is_refused(
    runner: Any, cli: Any, provider: Any, user: Any
) -> None:
    result = failed(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--redirect-uri",
            PASTE_REDIRECT,
            input=f"{PASTE_REDIRECT}?code=abc&state=forged\n",
        ),
        3,
    )

    assert "State mismatch" in result.output
    assert provider["token"].call_count == 0


def test_a_pasted_provider_error_is_reported(
    runner: Any, cli: Any, provider: Any, user: Any
) -> None:
    result = failed(
        login(
            runner,
            cli,
            *PROVIDER,
            *CLIENT,
            "--redirect-uri",
            PASTE_REDIRECT,
            input=f"{PASTE_REDIRECT}?error=access_denied\n",
        ),
        3,
    )

    assert "access_denied" in result.output
    assert provider["token"].call_count == 0
