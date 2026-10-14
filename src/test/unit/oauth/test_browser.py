"""Unit tests for `pctl.oauth.browser`: PKCE, the authorize URL and the redirect checks.

These are the parts of the browser login that decide whether it is safe, and none of them
needs a socket or a browser. The state check in particular is what stops a forged redirect
from being exchanged, so each way it can fail has a test of its own.
"""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest

from helpers import OAUTH_AUDIENCE, OAUTH_AUTHORIZE_URL, OAUTH_CLIENT_ID, OAUTH_TOKEN_URL
from pctl.config import OAuthConfig
from pctl.errors import AuthError
from pctl.oauth.browser import (
    DEFAULT_LOGIN_SCOPE,
    Pkce,
    authorize_url,
    check_redirect,
    is_loopback,
    new_pkce,
    parse_redirect,
)

pytestmark = pytest.mark.unit

REDIRECT = "http://127.0.0.1:8765/callback"
STATE = "state-value"


def config(**extra: str) -> OAuthConfig:
    return OAuthConfig.resolve(
        {
            "client_id": OAUTH_CLIENT_ID,
            "token_url": OAUTH_TOKEN_URL,
            "redirect_uri": REDIRECT,
            **extra,
        }
    )


def query_of(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


# ---------------------------------------------------------------------------
# pkce
# ---------------------------------------------------------------------------
def test_the_challenge_is_the_s256_hash_of_the_verifier() -> None:
    pkce = new_pkce()

    digest = hashlib.sha256(pkce.verifier.encode()).digest()
    assert pkce.challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_the_verifier_has_a_length_the_spec_allows() -> None:
    """RFC 7636 section 4.1: 43 to 128 characters from an unpadded URL-safe alphabet."""
    verifier = new_pkce().verifier

    assert 43 <= len(verifier) <= 128
    assert "=" not in verifier


def test_every_attempt_gets_its_own_secrets() -> None:
    first, second = new_pkce(), new_pkce()

    assert first.verifier != second.verifier
    assert first.state != second.state


# ---------------------------------------------------------------------------
# the authorize url
# ---------------------------------------------------------------------------
def test_the_authorize_url_asks_for_a_code_with_pkce() -> None:
    pkce = Pkce("verifier", "challenge", STATE)

    query = query_of(authorize_url(OAUTH_AUTHORIZE_URL, config(), pkce))

    assert query == {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": REDIRECT,
        "scope": DEFAULT_LOGIN_SCOPE,
        "state": STATE,
        "code_challenge": "challenge",
        "code_challenge_method": "S256",
    }


def test_the_verifier_is_never_put_in_the_url() -> None:
    """The verifier is the secret half of PKCE; only its hash may travel."""
    pkce = Pkce("do-not-send-me", "challenge", STATE)

    assert "do-not-send-me" not in authorize_url(OAUTH_AUTHORIZE_URL, config(), pkce)


def test_audience_and_scope_are_sent_when_given() -> None:
    pkce = Pkce("v", "c", STATE)

    query = query_of(
        authorize_url(OAUTH_AUTHORIZE_URL, config(audience=OAUTH_AUDIENCE, scope="read"), pkce)
    )

    assert query["audience"] == OAUTH_AUDIENCE
    assert query["scope"] == "read"


def test_an_authorize_url_that_already_has_a_query_is_extended() -> None:
    url = authorize_url(f"{OAUTH_AUTHORIZE_URL}?tenant=one", config(), Pkce("v", "c", STATE))

    assert url.startswith(f"{OAUTH_AUTHORIZE_URL}?tenant=one&response_type=code")


# ---------------------------------------------------------------------------
# reading what was pasted
# ---------------------------------------------------------------------------
def test_a_full_redirect_url_is_read() -> None:
    url = f"{REDIRECT}?code=abc&state={STATE}"

    assert parse_redirect(url) == {"code": "abc", "state": STATE}


def test_a_bare_query_string_is_read() -> None:
    assert parse_redirect("code=abc&state=xyz") == {"code": "abc", "state": "xyz"}


def test_a_query_string_with_a_leading_question_mark_is_read() -> None:
    assert parse_redirect("?code=abc") == {"code": "abc"}


def test_a_bare_code_is_read() -> None:
    assert parse_redirect("  abc123  ") == {"code": "abc123"}


def test_a_provider_error_is_read() -> None:
    parsed = parse_redirect(f"{REDIRECT}?error=access_denied&error_description=No+thanks")

    assert parsed == {"error": "access_denied", "error_description": "No thanks"}


# ---------------------------------------------------------------------------
# checking the redirect
# ---------------------------------------------------------------------------
def test_a_matching_state_yields_the_code() -> None:
    assert check_redirect({"code": "abc", "state": STATE}, STATE, require_state=True) == "abc"


def test_a_different_state_is_refused() -> None:
    """A redirect from some other login attempt, or a forged one."""
    with pytest.raises(AuthError, match="State mismatch"):
        check_redirect({"code": "abc", "state": "forged"}, STATE, require_state=True)


def test_a_different_state_is_refused_even_when_none_is_required() -> None:
    with pytest.raises(AuthError, match="State mismatch"):
        check_redirect({"code": "abc", "state": "forged"}, STATE, require_state=False)


def test_a_missing_state_is_refused_when_one_is_required() -> None:
    with pytest.raises(AuthError, match="no state"):
        check_redirect({"code": "abc"}, STATE, require_state=True)


def test_a_missing_state_is_accepted_for_a_pasted_code() -> None:
    """Someone who pastes only the code never saw the state, so none can be demanded."""
    assert check_redirect({"code": "abc"}, STATE, require_state=False) == "abc"


def test_a_provider_error_is_reported_with_its_description() -> None:
    params = {"error": "access_denied", "error_description": "The user said no"}

    with pytest.raises(AuthError, match="access_denied: The user said no"):
        check_redirect(params, STATE, require_state=True)


def test_a_provider_error_without_a_description_is_still_reported() -> None:
    with pytest.raises(AuthError, match="access_denied"):
        check_redirect({"error": "access_denied"}, STATE, require_state=False)


def test_a_provider_error_wins_over_a_code() -> None:
    with pytest.raises(AuthError, match="refused"):
        check_redirect({"error": "access_denied", "code": "abc"}, STATE, require_state=False)


def test_a_redirect_with_no_code_is_refused() -> None:
    with pytest.raises(AuthError, match="No authorization code"):
        check_redirect({"state": STATE}, STATE, require_state=True)


# ---------------------------------------------------------------------------
# loopback detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "uri",
    ["http://127.0.0.1:8765/callback", "http://localhost:3000/cb", "http://localhost:8080"],
)
def test_loopback_redirects_are_caught_locally(uri: str) -> None:
    assert is_loopback(uri) is True


@pytest.mark.parametrize(
    "uri",
    [
        "https://app.example.test/callback",
        "https://127.0.0.1:8765/callback",
        "http://192.168.1.10:8765/callback",
        "http://evil.example.test/callback",
        "http://localhost.evil.example.test/callback",
    ],
)
def test_anything_else_is_pasted_back(uri: str) -> None:
    """Only plain http to this machine can be listened for; a lookalike host never is."""
    assert is_loopback(uri) is False
