"""Catch the login redirect on a loopback address.

When the client's registered redirect is `http://127.0.0.1:PORT/path`, pctl can be the
thing that answers it: bind that port, wait for the browser to arrive, and read the code
from the query string, so nobody has to copy anything out of an address bar.

The listener is deliberately small. It binds only to 127.0.0.1, whatever host the redirect
names, serves exactly one path, and stops at the first request that carries parameters.
Anything else on the machine can still connect to it, which is why the caller refuses a
redirect whose `state` does not match.

Imported only by `oauth login`, so `http.server` is not paid for anywhere else.
"""

from __future__ import annotations

import socketserver
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..errors import AuthError, ConfigError

BIND_HOST = "127.0.0.1"
CLOSE_WINDOW_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>pctl</title>"
    b"<p>Login complete. You can close this window.</p>"
)


class _RedirectServer(HTTPServer):
    """An HTTP server that remembers which path to answer and what it was sent."""

    def __init__(self, port: int, expected_path: str) -> None:
        super().__init__((BIND_HOST, port), _Handler)
        self.expected_path = expected_path
        self.params: dict[str, str] = {}

    def server_bind(self) -> None:
        """Bind without the reverse DNS lookup `HTTPServer` does, which can stall for seconds."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = BIND_HOST, self.server_address[1]


class _Handler(BaseHTTPRequestHandler):
    server: _RedirectServer

    def do_GET(self) -> None:
        target = urlparse(self.path)
        if target.path != self.server.expected_path:
            self.send_error(404)
            return
        self.server.params.update({k: v[0] for k, v in parse_qs(target.query).items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(CLOSE_WINDOW_PAGE)))
        self.end_headers()
        self.wfile.write(CLOSE_WINDOW_PAGE)

    def log_message(self, format: str, *args: Any) -> None:
        """Say nothing: the redirect carries a code, and stderr is not the place for it."""


def wait_for_redirect(
    redirect_uri: str, timeout: float, on_listening: Callable[[], None]
) -> dict[str, str]:
    """Listen for the redirect, calling `on_listening` once it is safe for it to arrive.

    The browser is opened from `on_listening`, after the port is bound, so the redirect
    can never beat the listener to it.
    """
    parsed = urlparse(redirect_uri)
    if parsed.port is None:
        raise ConfigError(f"The loopback redirect {redirect_uri} needs an explicit port.")
    try:
        server = _RedirectServer(parsed.port, parsed.path or "/")
    except OSError as exc:
        raise ConfigError(
            f"Cannot listen on {parsed.netloc} for the login redirect: {exc}"
        ) from exc
    with server:
        on_listening()
        _serve_until_received(server, timeout)
    if not server.params:
        raise AuthError(f"No login redirect arrived within {timeout:g} seconds.")
    return server.params


def _serve_until_received(server: _RedirectServer, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not server.params and (remaining := deadline - time.monotonic()) > 0:
        server.timeout = remaining
        server.handle_request()
