"""Fixtures for the OAuth end-to-end tests.

Every test needs the same two things: an environment with no OAuth setting a developer's
shell might hold, and a respx router standing in for the provider. Neither is interesting
to the assertions, so both are fixtures.
"""

from __future__ import annotations

import socket
import threading
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

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
def free_port() -> int:
    """A port nothing is listening on, for a loopback redirect to claim.

    Found by binding port 0 and letting the kernel choose, then releasing it. Another
    process could take it in the gap, which is possible but vanishingly rare on a loopback
    address, and far less fragile than a hard-coded port that a developer's own tools may
    already hold.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class User:
    """Stands in for the person at the browser.

    `webbrowser.open` is replaced by `open`, which records the login page it was sent to
    and, when `reply` is set, follows the redirect the way a browser would after login:
    from a background thread, because the command is blocked waiting for exactly that.
    `reply` maps query parameters to values; a value of `None` leaves the parameter out,
    and `state` is filled in from the login page unless the test overrides it.
    """

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.reply: dict[str, str | None] | None = None
        self.failures: list[Exception] = []
        self._threads: list[threading.Thread] = []

    def open(self, url: str, *_args: Any, **_kwargs: Any) -> bool:
        self.opened.append(url)
        if self.reply is not None:
            thread = threading.Thread(target=self._follow, args=(url,))
            thread.start()
            self._threads.append(thread)
        return True

    @property
    def login_query(self) -> dict[str, str]:
        """The query string of the login page the command sent the user to."""
        return {k: v[0] for k, v in parse_qs(urlparse(self.opened[0]).query).items()}

    def finish(self) -> None:
        for thread in self._threads:
            thread.join(timeout=5)

    def _follow(self, url: str) -> None:
        query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        params = {"code": "auth-code", "state": query["state"], **(self.reply or {})}
        sent_params = {key: value for key, value in params.items() if value is not None}
        target = f"{query['redirect_uri']}?{urlencode(sent_params)}"
        # No proxies: a developer's HTTP_PROXY must not carry a request meant for loopback.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(target, timeout=5) as response:
                response.read()
        except OSError as exc:
            self.failures.append(exc)


@pytest.fixture
def user(monkeypatch: pytest.MonkeyPatch) -> Iterator[User]:
    """The person at the browser, joined after the test so no thread outlives it."""
    person = User()
    monkeypatch.setattr("webbrowser.open", person.open)
    yield person
    person.finish()


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
