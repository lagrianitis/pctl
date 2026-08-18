"""Unit tests for `pctl.tokencache`.

The cache holds a bearer token on disk, so two properties matter more than the
happy path: the file must not be readable by other users, and a token must be
treated as expired slightly before it really expires so it cannot die mid-request.
Corrupt or unreadable cache files must degrade to a cache miss rather than failing
the command.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import orjson
import pytest

from pctl.tokencache import (
    EXPIRY_SKEW_SECONDS,
    CachedToken,
    TokenCache,
    cache_dir,
    cache_key,
    clear_all,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TokenCache:
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path / "cache"))
    return TokenCache(cache_key("authority", "tenant", "client", "scope"))


def token(seconds_ahead: float = 3600, value: str = "tok") -> CachedToken:
    return CachedToken(access_token=value, expires_at=time.time() + seconds_ahead)


# ---------------------------------------------------------------------------
# CachedToken
# ---------------------------------------------------------------------------
def test_a_fresh_token_is_valid() -> None:
    assert token(3600).is_valid()


def test_an_expired_token_is_not_valid() -> None:
    assert not token(-1).is_valid()


def test_a_token_inside_the_skew_window_is_already_invalid() -> None:
    """Expiring in 60s with a 120s skew must count as expired."""
    assert not token(EXPIRY_SKEW_SECONDS - 60).is_valid()


def test_a_token_just_outside_the_skew_window_is_valid() -> None:
    assert token(EXPIRY_SKEW_SECONDS + 60).is_valid()


def test_an_empty_token_is_never_valid() -> None:
    assert not CachedToken(access_token="", expires_at=time.time() + 9999).is_valid()


def test_expires_in_never_goes_negative() -> None:
    assert token(-500).expires_in == 0


def test_expires_in_reports_remaining_seconds() -> None:
    assert 3500 <= token(3600).expires_in <= 3600


# ---------------------------------------------------------------------------
# keys and directories
# ---------------------------------------------------------------------------
def test_cache_key_is_deterministic() -> None:
    assert cache_key("a", "b") == cache_key("a", "b")


def test_cache_key_separates_different_inputs() -> None:
    assert cache_key("a", "b") != cache_key("b", "a")


def test_cache_key_treats_none_and_empty_alike() -> None:
    assert cache_key("a", None) == cache_key("a", "")


def test_cache_key_is_filename_safe_and_short() -> None:
    key = cache_key("tenant", "client")
    assert len(key) == 32
    assert key.isalnum()


def test_cache_dir_prefers_the_explicit_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCTL_CACHE_DIR", "/tmp/pctl-somewhere")
    assert cache_dir() == Path("/tmp/pctl-somewhere")


def test_cache_dir_falls_back_to_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PCTL_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg")
    assert cache_dir() == Path("/tmp/xdg/pctl")


def test_cache_dir_defaults_under_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PCTL_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert cache_dir() == Path.home() / ".cache" / "pctl"


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------
def test_store_then_load_returns_the_token(cache: TokenCache) -> None:
    cache.store(token(3600, "abc"))
    loaded = cache.load()
    assert loaded is not None
    assert loaded.access_token == "abc"


def test_load_is_a_miss_when_nothing_was_stored(cache: TokenCache) -> None:
    assert cache.load() is None


def test_an_expired_stored_token_is_a_miss(cache: TokenCache) -> None:
    cache.store(token(-10, "stale"))
    assert cache.load() is None


def test_a_token_inside_the_skew_window_is_a_miss(cache: TokenCache) -> None:
    cache.store(token(30, "nearly-stale"))
    assert cache.load() is None


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------
def test_the_cache_file_is_private(cache: TokenCache) -> None:
    cache.store(token())
    assert cache.path.stat().st_mode & 0o777 == 0o600


def test_the_cache_directory_is_private(cache: TokenCache) -> None:
    cache.store(token())
    assert cache.path.parent.stat().st_mode & 0o777 == 0o700


def test_no_temp_files_are_left_behind(cache: TokenCache) -> None:
    """The write goes through a temp file; it must be renamed, not abandoned."""
    cache.store(token())
    assert [p.name for p in cache.path.parent.iterdir()] == [cache.path.name]


# ---------------------------------------------------------------------------
# resilience
# ---------------------------------------------------------------------------
def test_corrupt_json_is_a_miss_not_a_crash(cache: TokenCache) -> None:
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_bytes(b"{ not json")
    assert cache.load() is None


def test_a_valid_json_object_with_wrong_fields_is_a_miss(cache: TokenCache) -> None:
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_bytes(orjson.dumps({"unexpected": True}))
    assert cache.load() is None


def test_a_non_numeric_expiry_is_a_miss(cache: TokenCache) -> None:
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_bytes(orjson.dumps({"access_token": "x", "expires_at": "soon"}))
    assert cache.load() is None


def test_an_unwritable_directory_does_not_fail_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caching is an optimisation, so a read-only home must not break anything."""
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    monkeypatch.setenv("PCTL_CACHE_DIR", str(locked / "cache"))
    try:
        cache = TokenCache(cache_key("t"))
        cache.store(token())
        assert cache.load() is None
    finally:
        os.chmod(locked, 0o700)


# ---------------------------------------------------------------------------
# disabling and clearing
# ---------------------------------------------------------------------------
def test_a_disabled_cache_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path / "cache"))
    cache = TokenCache(cache_key("t"), enabled=False)
    cache.store(token())
    assert not cache.path.exists()


def test_a_disabled_cache_never_reads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path / "cache"))
    TokenCache(cache_key("t")).store(token())
    assert TokenCache(cache_key("t"), enabled=False).load() is None


def test_clear_removes_the_file(cache: TokenCache) -> None:
    cache.store(token())
    assert cache.clear() is True
    assert not cache.path.exists()


def test_clear_on_a_missing_file_is_false_not_an_error(cache: TokenCache) -> None:
    assert cache.clear() is False


def test_clear_all_counts_what_it_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path / "cache"))
    for name in ("one", "two", "three"):
        TokenCache(cache_key(name)).store(token())
    assert clear_all() == 3
    assert clear_all() == 0


def test_clear_all_on_a_missing_directory_is_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path / "never-created"))
    assert clear_all() == 0


def test_different_tenants_do_not_share_a_cache_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PCTL_CACHE_DIR", str(tmp_path / "cache"))
    TokenCache(cache_key("tenant-a")).store(token(3600, "a-token"))
    assert TokenCache(cache_key("tenant-b")).load() is None
