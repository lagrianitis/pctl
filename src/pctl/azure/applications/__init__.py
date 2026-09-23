"""The `apps` service under the `azure` case: application registrations.

Read-only. The portal calls these App registrations, and calls their tenant-local
instances Enterprise applications, which live under `pctl azure sp`. One application can
have a service principal in many tenants; the two are joined by `appId`.

`__init__.py` declares the service group and its actions; shared code lives in
`common.py`, because a package namespace also receives its submodules as attributes and
would shadow builtins of the same name.
"""

from __future__ import annotations

import click

from ...lazy import PctlGroup
from .common import DEFAULT_LIST_COLUMNS, match_option, resolve_application

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "list": (
        "pctl.azure.applications.list:command",
        "List application registrations in the tenant.",
    ),
    "get": (
        "pctl.azure.applications.get:command",
        "Show an app registration by name, appId or object ID.",
    ),
}


@click.group(name="apps", cls=PctlGroup, lazy_subcommands=LAZY_SUBCOMMANDS)
def applications() -> None:
    """Application registrations, the app objects behind service principals."""


__all__ = [
    "DEFAULT_LIST_COLUMNS",
    "applications",
    "match_option",
    "resolve_application",
]
