"""On-disk access token cache.

A client-credentials token round trip to Entra ID costs 150-400ms, which is often
more than the Graph call itself. Caching it makes repeated invocations feel
instant. The cache holds a bearer token, so the file is created 0600 inside a 0700
directory and can be disabled with `--no-token-cache` or `PCTL_NO_TOKEN_CACHE=1`.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import orjson

# Refresh a little before real expiry so a token cannot die mid-request.
EXPIRY_SKEW_SECONDS = 120


@dataclass(slots=True, frozen=True)
class CachedToken:
    access_token: str
    expires_at: float

    @property
    def expires_in(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def is_valid(self, *, skew: int = EXPIRY_SKEW_SECONDS) -> bool:
        return bool(self.access_token) and self.expires_at - skew > time.time()


def cache_dir() -> Path:
    override = os.environ.get("PCTL_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "pctl"


def cache_key(*parts: str | None) -> str:
    digest = hashlib.sha256("\x1f".join(p or "" for p in parts).encode()).hexdigest()
    return digest[:32]


class TokenCache:
    """Single-file JSON cache keyed by tenant/client/scope."""

    def __init__(self, key: str, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.path = cache_dir() / "tokens" / f"{key}.json"

    def load(self) -> CachedToken | None:
        if not self.enabled:
            return None
        try:
            raw = self.path.read_bytes()
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return None
        try:
            payload = orjson.loads(raw)
            token = CachedToken(
                access_token=str(payload["access_token"]),
                expires_at=float(payload["expires_at"]),
            )
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        return token if token.is_valid() else None

    def store(self, token: CachedToken) -> None:
        if not self.enabled:
            return
        payload = orjson.dumps({
            "access_token": token.access_token,
            "expires_at": token.expires_at,
        })
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Write via a temp file in the same directory so a concurrent reader
            # never observes a partial token.
            fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".tok-")
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        except OSError:
            # A cache is an optimisation; failing to persist must not fail the command.
            pass

    def clear(self) -> bool:
        try:
            self.path.unlink()
            return True
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            return False


def clear_all() -> int:
    """Delete every cached token. Returns the number of files removed."""
    tokens = cache_dir() / "tokens"
    removed = 0
    if not tokens.is_dir():
        return 0
    for entry in tokens.glob("*.json"):
        try:
            entry.unlink()
            removed += 1
        except OSError:
            pass
    return removed
