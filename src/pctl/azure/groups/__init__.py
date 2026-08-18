"""The `groups` service under the `azure` case.

`__init__.py` declares the service group and its actions; the code those actions
share lives in `common.py`, because a package namespace also receives its
submodules as attributes (`groups.list`) and would shadow builtins of the same
name.
"""

from __future__ import annotations

import click

from ...lazy import PctlGroup
from .common import (
    DEFAULT_LIST_COLUMNS,
    DEFAULT_MEMBER_COLUMNS,
    MATCH_MODES,
    add_relations,
    match_option,
    resolve_one,
)

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "list": ("pctl.azure.groups.list:command", "List every group in the tenant, paginated."),
    "get": ("pctl.azure.groups.get:command", "Show details for groups by display name."),
    "members": ("pctl.azure.groups.members:command", "Stream a group's members or owners."),
}


@click.group(name="groups", cls=PctlGroup, lazy_subcommands=LAZY_SUBCOMMANDS)
def groups() -> None:
    """List and inspect Entra ID groups."""


__all__ = [
    "DEFAULT_LIST_COLUMNS",
    "DEFAULT_MEMBER_COLUMNS",
    "MATCH_MODES",
    "add_relations",
    "groups",
    "match_option",
    "resolve_one",
]
