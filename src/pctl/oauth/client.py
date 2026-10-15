"""Token endpoint transport for the `oauth` case.

Actions never talk to the provider directly: they ask this client for a token. It owns
where the endpoints are, the form-encoded requests RFC 6749 specifies, the mapping of
provider failures onto the documented exit codes, and the on-disk cache for machine tokens.

Synchronous on purpose. A token is one request, so there is no concurrency to win and no
event loop to start, which keeps `oauth token` as quick as the provider allows. `httpx`
is imported inside the methods that use it, so `pctl oauth --help` never pays for it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import OAuthConfig
from ..errors import AuthError, ConfigError
from ..tokencache import CachedToken, TokenCache, cache_key

if TYPE_CHECKING:
    import httpx

TOKEN_PATH = "/oauth/token"
AUTHORIZE_PATH = "/authorize"
CONNECT_TIMEOUT = 10.0
ERROR_BODY_LIMIT = 200


@dataclass(slots=True, frozen=True)
class Endpoints:
    """Where to send the user and where to exchange what comes back."""

    token_url: str
    authorize_url: str | None


class OAuthClient:
    """One provider, one client id. Use as a context manager so the connection closes."""

    def __init__(self, config: OAuthConfig, *, timeout: float, log: Callable[[str], None]) -> None:
        self.config = config
        self.timeout = timeout
        self._log = log
        self._http: httpx.Client | None = None

    def __enter__(self) -> OAuthClient:
        import httpx

        self._http = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=min(CONNECT_TIMEOUT, self.timeout)),
            headers={"Accept": "application/json"},
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._http is not None:
            self._http.close()

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            raise RuntimeError("OAuthClient must be used as a context manager")
        return self._http

    # -- endpoints --------------------------------------------------------
    def endpoints(self, *, authorize: bool = False) -> Endpoints:
        """The token endpoint, and the authorize endpoint when `authorize` is set.

        An explicit URL wins. Otherwise each endpoint is the issuer plus its conventional
        path, `/oauth/token` and `/authorize`, which is how Auth0 lays them out. No request
        is made: a provider with a different layout is reached by naming its URLs.
        """
        base = (self.config.issuer or "").rstrip("/")
        token_url = self.config.token_url or (base + TOKEN_PATH if base else None)
        authorize_url = self.config.authorize_url or (base + AUTHORIZE_PATH if base else None)
        if not token_url:
            raise ConfigError("No token endpoint. Pass --token-url or an --issuer.")
        if authorize and not authorize_url:
            raise ConfigError("No authorize endpoint. Pass --authorize-url or an --issuer.")
        return Endpoints(token_url, authorize_url)

    # -- grants -----------------------------------------------------------
    def client_credentials(self) -> CachedToken:
        """A machine token, from the cache when a valid one is on disk."""
        cache = TokenCache(self._cache_key(), enabled=self.config.use_token_cache)
        if (cached := cache.load()) is not None:
            self._log(f"using cached token (expires in {cached.expires_in}s)")
            return cached
        token = self._request(self.endpoints().token_url, self._credentials_form())
        cache.store(token)
        return token

    def exchange_code(self, code: str, verifier: str) -> CachedToken:
        """Trade an authorization code for a user token. Never cached."""
        config = self.config
        form = {
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": config.redirect_uri or "",
        }
        if config.client_secret:
            form["client_secret"] = config.client_secret
        return self._request(self.endpoints().token_url, form)

    def _credentials_form(self) -> dict[str, str]:
        config = self.config
        form = {
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.require_client_secret(),
        }
        optional = {"audience": config.audience, "scope": config.scope}
        return form | {key: value for key, value in optional.items() if value}

    def _cache_key(self) -> str:
        """Identify a token by who asked for what, never by the secret.

        Built from configuration alone, so a cache hit needs nothing resolved first.
        """
        config = self.config
        return cache_key(
            "oauth",
            config.issuer,
            config.token_url,
            config.client_id,
            config.audience,
            config.scope,
        )

    def _request(self, url: str, form: dict[str, str]) -> CachedToken:
        import httpx

        self._log(f"POST {url} ({form['grant_type']})")
        try:
            response = self.http.post(url, data=form)
        except httpx.HTTPError as exc:
            raise AuthError(f"Could not reach the token endpoint: {exc}") from exc
        if response.status_code != 200:
            raise AuthError(f"Token request failed ({response.status_code}): {_describe(response)}")
        return _parse_token(response)


def _parse_token(response: httpx.Response) -> CachedToken:
    """Read the access token and its lifetime from a successful response."""
    try:
        payload = response.json()
    except ValueError as exc:
        raise AuthError("The token endpoint did not return JSON.") from exc
    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    if not access_token:
        raise AuthError("The token endpoint returned no access_token.")
    lifetime = float(payload.get("expires_in") or 0)
    return CachedToken(access_token=access_token, expires_at=time.time() + lifetime)


def _describe(response: httpx.Response) -> str:
    """The provider's own error, which is what tells you whether it was the secret."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:ERROR_BODY_LIMIT] or response.reason_phrase
    if isinstance(body, dict):
        parts = [str(body[key]) for key in ("error", "error_description") if body.get(key)]
        if parts:
            return ": ".join(parts)
    return response.text[:ERROR_BODY_LIMIT]
