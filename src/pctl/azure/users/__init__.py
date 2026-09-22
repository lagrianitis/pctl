"""The `users` service under the `azure` case.

Only `get` for now: resolve a person to their directory object from whatever you happen
to know about them, which is usually an email address.

`__init__.py` declares the service group and its actions; shared code lives in
`common.py`, because a package namespace also receives its submodules as attributes and
would shadow builtins of the same name.
"""

from __future__ import annotations

import click

from ...lazy import PctlGroup
from .common import DEFAULT_LIST_COLUMNS, match_option

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "get": (
        "pctl.azure.users.get:command",
        "Show a user, found by email, display name or object ID.",
    ),
}


@click.group(name="users", cls=PctlGroup, lazy_subcommands=LAZY_SUBCOMMANDS)
def users() -> None:
    """Entra ID users."""


__all__ = ["DEFAULT_LIST_COLUMNS", "match_option", "users"]
