"""pctl - a fast CLI for Microsoft Graph groups and AWS DynamoDB.

The version is not written here. `pyproject.toml` is the single source of truth and the
installed package metadata is generated from it, so `__version__` reads that metadata.
It is resolved on first access instead of at import, because `importlib.metadata` costs
startup time that `pctl --help` should not pay.
"""

from __future__ import annotations

__all__ = ["__version__"]


def __getattr__(name: str) -> str:
    if name == "__version__":
        from importlib.metadata import version

        return version("pctl")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
