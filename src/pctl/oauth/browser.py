"""The browser half of `oauth login`: PKCE, the authorize URL and reading the redirect.

Everything here is a pure function except `open_browser`, which is why the whole flow can
be tested without a browser. The one piece that needs a socket, catching the redirect on a
loopback address, lives in `loopback.py` so `http.server` is only imported when it is used.

PKCE (RFC 7636) is what makes the authorization code worthless to anyone who intercepts
it: the code can only be exchanged by whoever holds the verifier, and that never leaves
this process. The `state` value binds the redirect to this login attempt.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

import click

from ..config import OAuthConfig
from ..errors import AuthError

DEFAULT_LOGIN_SCOPE = "openid profile email"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")

# RFC 7636 asks for a verifier of 43 to 128 characters; 64 random bytes encode to 86.
VERIFIER_BYTES = 64
STATE_BYTES = 16


@dataclass(slots=True, frozen=True)
class Pkce:
    """The secrets of one login attempt. None of them is ever written to disk."""

    verifier: str
    challenge: str
    state: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_pkce() -> Pkce:
    """A fresh verifier, its S256 challenge, and a state value."""
    verifier = _b64url(secrets.token_bytes(VERIFIER_BYTES))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return Pkce(verifier, challenge, _b64url(secrets.token_bytes(STATE_BYTES)))


def authorize_url(base: str, config: OAuthConfig, pkce: Pkce) -> str:
    """The address to send the user to. `audience` is sent only when one is set."""
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri or "",
        "scope": config.scope or DEFAULT_LOGIN_SCOPE,
        "state": pkce.state,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
    }
    if config.audience:
        params["audience"] = config.audience
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode(params)}"


def parse_redirect(value: str) -> dict[str, str]:
    """Accept a full redirect URL, a bare query string, or just the authorization code."""
    value = value.strip()
    if "code=" in value or "error=" in value:
        query = urlparse(value).query or value.lstrip("?")
        return {key: values[0] for key, values in parse_qs(query).items()}
    return {"code": value}


def check_redirect(params: Mapping[str, str], state: str, *, require_state: bool) -> str:
    """The authorization code, once the redirect has been shown to be ours and a success.

    A `state` that is present must match. One that is absent is accepted only when the
    caller could not have had it, which is a code pasted by hand; a redirect caught on the
    loopback listener always carries one, so its absence is refused.
    """
    if "error" in params:
        detail = ": ".join(filter(None, [params["error"], params.get("error_description")]))
        raise AuthError(f"The provider refused the login: {detail}")
    returned = params.get("state")
    if returned is None and require_state:
        raise AuthError("The redirect carried no state, so it cannot be tied to this login.")
    if returned is not None and not secrets.compare_digest(returned.encode(), state.encode()):
        raise AuthError("State mismatch: this redirect is not from this login attempt.")
    code = params.get("code")
    if not code:
        raise AuthError("No authorization code found in the redirect.")
    return code


def is_loopback(redirect_uri: str) -> bool:
    """Whether the redirect points back at this machine, where pctl can listen for it."""
    parsed = urlparse(redirect_uri)
    return parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS


def open_browser(url: str) -> None:
    """Open the login page, and print it as well for when no browser can be opened."""
    import webbrowser

    click.echo("Opening the browser to log in...", err=True)
    click.echo(f"If it does not open, visit:\n{url}\n", err=True)
    webbrowser.open(url)
