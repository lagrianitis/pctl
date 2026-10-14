"""Fixtures for the OAuth end-to-end tests.

Every test needs the same two things: an environment with no OAuth setting a developer's
shell might hold, and a respx router standing in for the provider. Neither is interesting
to the assertions, so both are fixtures.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

from helpers import FAKE_JWT, OAUTH_TOKEN_URL

OAUTH_ENV = (
    "OAUTH_ISSUER",
    "OAUTH_TOKEN_URL",
    "OAUTH_AUTHORIZE_URL",
    "OAUTH_CLIENT_ID",
    "OAUTH_CLIENT_SECRET",
    "OAUTH_AUDIENCE",
    "OAUTH_SCOPE",
    "OAUTH_REDIRECT_URI",
    "OAUTH_LOGIN_TIMEOUT",
    "PCTL_OAUTH_SECRET_ID",
    "PCTL_SECRET_REGION",
    "PCTL_NO_TOKEN_CACHE",
)


@pytest.fixture(autouse=True)
def oauth_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A clean OAuth environment and a private token cache, yielding the cache directory.

    Autouse because a variable left in a developer's shell would silently supply a
    setting the test meant to leave out, and a shared cache would let one test's token
    answer another's request.
    """
    for name in OAUTH_ENV:
        monkeypatch.delenv(name, raising=False)
    cache = tmp_path / "cache"
    monkeypatch.setenv("PCTL_CACHE_DIR", str(cache))
    return cache


@pytest.fixture
def provider() -> Iterator[Any]:
    """A respx router with the token endpoint answered, named `token`.

    The token is `FAKE_JWT` with an hour to live. Look the route up as
    `provider["token"]` to count requests or read the form a command sent.

    `assert_all_called=False`: a test registers the routes it might need, and most only
    reach some of them.
    """
    import httpx
    import respx

    with respx.mock(assert_all_called=False) as router:
        router.post(OAUTH_TOKEN_URL, name="token").mock(
            return_value=httpx.Response(200, json={"access_token": FAKE_JWT, "expires_in": 3600})
        )
        yield router


@pytest.fixture
def sent() -> Callable[[Any], dict[str, str]]:
    """Read the form fields of the last request a route received.

    Token requests are form-encoded, so the body is a query string. A field the command
    did not send is simply absent from the result, which is how a test asserts that an
    optional setting was left out.
    """

    def read(route: Any) -> dict[str, str]:
        body = route.calls.last.request.content.decode()
        return {key: values[0] for key, values in parse_qs(body).items()}

    return read
