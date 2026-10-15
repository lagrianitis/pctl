"""Unit tests for where `OAuthClient` looks for the endpoints.

Working them out makes no request, so the client is used without being entered. The rule
is simple and everything depends on it: an explicit URL wins, otherwise the issuer plus the
conventional path.
"""

from __future__ import annotations

import pytest

from helpers import OAUTH_AUTHORIZE_URL, OAUTH_CLIENT_ID, OAUTH_ISSUER, OAUTH_TOKEN_URL
from pctl.config import OAuthConfig
from pctl.errors import ConfigError
from pctl.oauth.client import OAuthClient

pytestmark = pytest.mark.unit


def client(**settings: str) -> OAuthClient:
    config = OAuthConfig.resolve({"client_id": OAUTH_CLIENT_ID, **settings})
    return OAuthClient(config, timeout=5.0, log=lambda _message: None)


def test_the_issuer_gives_both_endpoints() -> None:
    endpoints = client(issuer=OAUTH_ISSUER).endpoints(authorize=True)

    assert endpoints.token_url == OAUTH_TOKEN_URL
    assert endpoints.authorize_url == OAUTH_AUTHORIZE_URL


@pytest.mark.parametrize("issuer", [f"{OAUTH_ISSUER}/", f"{OAUTH_ISSUER}//"])
def test_trailing_slashes_on_the_issuer_do_not_double_up(issuer: str) -> None:
    endpoints = client(issuer=issuer).endpoints(authorize=True)

    assert endpoints.token_url == OAUTH_TOKEN_URL
    assert endpoints.authorize_url == OAUTH_AUTHORIZE_URL


def test_an_explicit_token_url_beats_the_issuer() -> None:
    endpoints = client(issuer=OAUTH_ISSUER, token_url="https://other.example.test/t").endpoints()

    assert endpoints.token_url == "https://other.example.test/t"


def test_an_explicit_authorize_url_beats_the_issuer() -> None:
    endpoints = client(issuer=OAUTH_ISSUER, authorize_url="https://other.example.test/a").endpoints(
        authorize=True
    )

    assert endpoints.authorize_url == "https://other.example.test/a"
    assert endpoints.token_url == OAUTH_TOKEN_URL


def test_the_two_urls_alone_need_no_issuer() -> None:
    oauth = client(token_url="https://t.example.test/t", authorize_url="https://a.example.test/a")

    resolved = oauth.endpoints(authorize=True)
    assert (resolved.token_url, resolved.authorize_url) == (
        "https://t.example.test/t",
        "https://a.example.test/a",
    )


def test_a_token_url_alone_is_enough_for_a_machine_token() -> None:
    endpoints = client(token_url="https://t.example.test/t").endpoints()

    assert endpoints.authorize_url is None


def test_a_login_with_no_authorize_endpoint_is_a_usage_error() -> None:
    with pytest.raises(ConfigError, match="authorize endpoint"):
        client(token_url="https://t.example.test/t").endpoints(authorize=True)
