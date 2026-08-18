"""Async Microsoft Graph client.

Speed comes from four places:

1. One `httpx.AsyncClient` with keep-alive (and HTTP/2 when `h2` is installed), so
   TLS is negotiated once per process.
2. Tokens cached on disk between invocations (see `tokencache`).
3. Page prefetching: `@odata.nextLink` is inherently sequential, so page N+1 is
   requested while page N is still being consumed. That hides one full round trip
   per page.
4. `$top=999` plus `$select` to cut both the number of pages and the bytes per page.

Throttling is expected on large tenants, so 429/5xx are retried with `Retry-After`
honoured and exponential backoff with jitter otherwise.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any, Self

import httpx

from ..config import GRAPH_MAX_PAGE_SIZE, AzureConfig
from ..errors import AuthError, UpstreamError
from ..tokencache import CachedToken, TokenCache, cache_key

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
MAX_BACKOFF = 20.0

DEFAULT_GROUP_SELECT: tuple[str, ...] = (
    "id",
    "displayName",
    "mail",
    "description",
    "groupTypes",
    "securityEnabled",
    "createdDateTime",
)
DEFAULT_MEMBER_SELECT: tuple[str, ...] = (
    "id",
    "displayName",
    "userPrincipalName",
    "mail",
)

# `$search`, `$count` and `endsWith` filters require the advanced query API.
ADVANCED_QUERY_HEADERS = {"ConsistencyLevel": "eventual"}


def escape_odata(value: str) -> str:
    """Escape a string literal for an OData filter (single quotes are doubled)."""
    return value.replace("'", "''")


def _http2_available() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


class GraphClient:
    """Minimal, fast Graph client scoped to what this CLI needs."""

    def __init__(
        self,
        config: AzureConfig,
        *,
        timeout: float = 30.0,
        concurrency: int = 16,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.timeout = timeout
        self.concurrency = max(1, concurrency)
        self._log = log or (lambda _msg: None)
        self._client: httpx.AsyncClient | None = None
        self._token: CachedToken | None = None
        self._token_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._cache = TokenCache(
            cache_key(config.authority, config.tenant_id, config.client_id, config.scope),
            enabled=config.use_token_cache,
        )
        self._credential: Any = None

    # -- lifecycle --------------------------------------------------------
    async def __aenter__(self) -> Self:
        limits = httpx.Limits(
            max_connections=self.concurrency + 4,
            max_keepalive_connections=self.concurrency + 4,
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            limits=limits,
            http2=_http2_available(),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._credential is not None:
            close = getattr(self._credential, "close", None)
            if close is not None:
                await close()
            self._credential = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GraphClient must be used as an async context manager")
        return self._client

    # -- auth -------------------------------------------------------------
    async def token(self) -> CachedToken:
        if self._token is not None and self._token.is_valid():
            return self._token
        async with self._token_lock:
            if self._token is not None and self._token.is_valid():
                return self._token
            cached = self._cache.load()
            if cached is not None:
                self._log(f"using cached token (expires in {cached.expires_in}s)")
                self._token = cached
                return cached
            token = await self._acquire_token()
            self._cache.store(token)
            self._token = token
            return token

    async def _acquire_token(self) -> CachedToken:
        if self.config.has_client_secret:
            return await self._acquire_client_credentials()
        return await self._acquire_via_azure_identity()

    async def _acquire_client_credentials(self) -> CachedToken:
        self._log(f"requesting token from {self.config.token_endpoint}")
        try:
            response = await self.http.post(
                self.config.token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.config.client_id or "",
                    "client_secret": self.config.client_secret or "",
                    "scope": self.config.scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"Could not reach the token endpoint: {exc}") from exc

        if response.status_code != 200:
            raise AuthError(f"Token request failed ({response.status_code}): {_describe(response)}")
        payload = response.json()
        access_token = payload.get("access_token")
        if not access_token:
            raise AuthError("Token endpoint returned no access_token")
        return CachedToken(
            access_token=access_token,
            expires_at=time.time() + float(payload.get("expires_in", 3600)),
        )

    async def _acquire_via_azure_identity(self) -> CachedToken:
        """Fall back to azure-identity, which covers `az login`, managed identity, etc."""
        try:
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as exc:
            raise AuthError(
                "No client secret found and azure-identity is not installed.\n"
                "Either set AZURE_CLIENT_ID and AZURE_CLIENT_SECRET, or install the "
                "fallback credential chain with: pip install 'pctl[azure]'"
            ) from exc

        self._log("acquiring token via azure-identity DefaultAzureCredential")
        credential = DefaultAzureCredential()
        self._credential = credential
        try:
            result = await credential.get_token(self.config.scope)
        except Exception as exc:  # azure-identity raises a broad ClientAuthenticationError
            raise AuthError(f"azure-identity could not get a token: {exc}") from exc
        return CachedToken(access_token=result.token, expires_at=float(result.expires_on))

    def clear_cached_token(self) -> bool:
        self._token = None
        return self._cache.clear()

    # -- requests ---------------------------------------------------------
    async def _authorized_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        token = await self.token()
        headers = {"Authorization": f"Bearer {token.access_token}"}
        if extra:
            headers.update(extra)
        return headers

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send an authorized request, retrying throttling and transient failures."""
        target = url if url.startswith("http") else f"{self.config.base_url}/{url.lstrip('/')}"
        last_error: str = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            async with self._semaphore:
                try:
                    response = await self.http.request(
                        method,
                        target,
                        params=params,
                        headers=await self._authorized_headers(headers),
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = str(exc)
                    if attempt == MAX_ATTEMPTS:
                        raise UpstreamError(f"Request to {target} failed: {exc}") from exc
                    await self._sleep_backoff(attempt, None)
                    continue

            if response.status_code == 401:
                # Token may have been revoked or the cached copy is stale.
                if attempt == 1:
                    self._log("got 401, discarding cached token and retrying")
                    self.clear_cached_token()
                    continue
                raise AuthError(f"Graph rejected the token: {_describe(response)}")

            if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                retry_after = response.headers.get("Retry-After")
                self._log(
                    f"{response.status_code} from Graph, retry {attempt}/{MAX_ATTEMPTS - 1}"
                    + (f" after {retry_after}s" if retry_after else "")
                )
                await self._sleep_backoff(attempt, retry_after)
                continue

            if response.status_code >= 400:
                raise UpstreamError(
                    f"Graph returned {response.status_code} for {target}: {_describe(response)}"
                )
            return response

        raise UpstreamError(
            f"Request to {target} failed after {MAX_ATTEMPTS} attempts: {last_error}"
        )

    @staticmethod
    async def _sleep_backoff(attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                await asyncio.sleep(min(float(retry_after), MAX_BACKOFF))
                return
            except ValueError:
                pass
        delay = min(MAX_BACKOFF, (2 ** (attempt - 1)) * 0.5)
        await asyncio.sleep(delay + random.uniform(0, 0.25))

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self.request("GET", url, params=params, headers=headers)
        if not response.content:
            return {}
        return response.json()

    async def paginate(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every item across `@odata.nextLink` pages, prefetching the next page."""
        page_task: asyncio.Task[dict[str, Any]] | None = asyncio.create_task(
            self.get_json(url, params=params, headers=headers)
        )
        yielded = 0
        pages = 0
        try:
            while page_task is not None:
                payload = await page_task
                page_task = None
                pages += 1
                items = payload.get("value") or []
                next_link = payload.get("@odata.nextLink")
                if next_link:
                    # Kick off the next page before handing items to the consumer.
                    page_task = asyncio.create_task(self.get_json(next_link, headers=headers))
                self._log(f"page {pages}: {len(items)} items")
                for item in items:
                    yield item
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
        finally:
            # The consumer stopped early (limit reached, or an exception upstream):
            # discard the page that is already in flight.
            if page_task is not None:
                page_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await page_task

    # -- groups -----------------------------------------------------------
    def _list_params(
        self,
        *,
        select: Sequence[str] | None,
        filter_expr: str | None,
        search: str | None,
        order_by: str | None,
        page_size: int,
        count: bool,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        params: dict[str, Any] = {"$top": min(page_size, GRAPH_MAX_PAGE_SIZE)}
        if select:
            params["$select"] = ",".join(select)
        if filter_expr:
            params["$filter"] = filter_expr
        if search:
            params["$search"] = search if search.startswith('"') else f'"displayName:{search}"'
        if order_by:
            params["$orderby"] = order_by
        headers: dict[str, str] = {}
        # Graph's advanced query capability is required for $search and for
        # $orderby combined with $filter; it needs both the header and $count=true.
        if search or count or (order_by and filter_expr):
            headers.update(ADVANCED_QUERY_HEADERS)
            params["$count"] = "true"
        return params, headers

    def list_groups(
        self,
        *,
        select: Sequence[str] | None = DEFAULT_GROUP_SELECT,
        filter_expr: str | None = None,
        search: str | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        page_size: int = GRAPH_MAX_PAGE_SIZE,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream every group in the tenant (or those matching a filter/search)."""
        params, headers = self._list_params(
            select=select,
            filter_expr=filter_expr,
            search=search,
            order_by=order_by,
            page_size=page_size,
            count=False,
        )
        return self.paginate("groups", params=params, headers=headers, limit=limit)

    async def count_groups(self, *, filter_expr: str | None = None) -> int:
        """Ask Graph for a count without transferring the objects."""
        params: dict[str, Any] = {"$count": "true", "$top": 1, "$select": "id"}
        if filter_expr:
            params["$filter"] = filter_expr
        payload = await self.get_json("groups", params=params, headers=ADVANCED_QUERY_HEADERS)
        return int(payload.get("@odata.count", 0))

    async def find_groups_by_display_name(
        self,
        display_name: str,
        *,
        mode: str = "exact",
        select: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve a display name to zero or more groups.

        `mode` is one of `exact` (`displayName eq`), `prefix` (`startswith`) or
        `search` (Graph full-text `$search`, which also matches substrings).
        """
        literal = escape_odata(display_name)
        filter_expr: str | None = None
        search: str | None = None
        match mode:
            case "exact":
                filter_expr = f"displayName eq '{literal}'"
            case "prefix":
                filter_expr = f"startswith(displayName,'{literal}')"
            case "search":
                search = f'"displayName:{literal}"'
            case _:
                raise ValueError(f"unknown match mode: {mode}")

        params, headers = self._list_params(
            select=select,
            filter_expr=filter_expr,
            search=search,
            order_by=None,
            page_size=GRAPH_MAX_PAGE_SIZE,
            count=False,
        )
        return [
            item
            async for item in self.paginate("groups", params=params, headers=headers, limit=limit)
        ]

    async def get_group(
        self, group_id: str, *, select: Sequence[str] | None = None
    ) -> dict[str, Any]:
        params = {"$select": ",".join(select)} if select else None
        return await self.get_json(f"groups/{group_id}", params=params)

    async def relation(
        self,
        group_id: str,
        relation: str,
        *,
        select: Sequence[str] | None = DEFAULT_MEMBER_SELECT,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Collect a group relation: `members`, `owners` or `transitiveMembers`."""
        params: dict[str, Any] = {"$top": GRAPH_MAX_PAGE_SIZE}
        if select:
            params["$select"] = ",".join(select)
        return [
            item
            async for item in self.paginate(
                f"groups/{group_id}/{relation}", params=params, limit=limit
            )
        ]

    async def relation_count(self, group_id: str, relation: str) -> int | None:
        """Use the `/$count` endpoint, which returns a bare integer body."""
        try:
            response = await self.request(
                "GET",
                f"groups/{group_id}/{relation}/$count",
                headers=ADVANCED_QUERY_HEADERS,
            )
        except UpstreamError:
            return None
        try:
            return int(response.text.strip())
        except TypeError, ValueError:
            return None


def _describe(response: httpx.Response) -> str:
    """Pull the human-readable bit out of a Graph or Entra ID error body."""
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:400] if text else response.reason_phrase
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)[:400]
        if isinstance(error, str):
            description = payload.get("error_description") or error
            return str(description).splitlines()[0][:400]
    return str(payload)[:400]


def run(coro: Any) -> Any:
    """Run a coroutine, preferring uvloop when it is installed."""
    try:
        import uvloop
    except ImportError:
        return asyncio.run(coro)
    return uvloop.run(coro)
