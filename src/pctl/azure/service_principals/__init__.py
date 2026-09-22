"""The `sp` service under the `azure` case: service principals.

Graph calls them service principals; the Entra ID portal calls them Enterprise
Applications. Both names reach this group, so `pctl azure enterprise-apps` works too.

`__init__.py` declares the service group and its actions; shared code lives in
`common.py`, because a package namespace also receives its submodules as attributes
(`service_principals.list`) and would shadow builtins of the same name.
"""

from __future__ import annotations

import click

from ...lazy import PctlGroup
from .common import (
    DEFAULT_LIST_COLUMNS,
    MATCH_MODES,
    OWNER_TYPES,
    PRINCIPAL_MATCH_MODES,
    collect_owners,
    filter_by_principal,
    label_roles,
    looks_like_email,
    looks_like_object_id,
    match_option,
    owner_label,
    resolve_one,
    resolve_owner,
    resolve_owners,
)

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "list": (
        "pctl.azure.service_principals.list:command",
        "List service principals in the tenant, paginated.",
    ),
    "get": (
        "pctl.azure.service_principals.get:command",
        "Show details for service principals by display name.",
    ),
    "assignments": (
        "pctl.azure.service_principals.assignments:command",
        "List app role assignments for an Enterprise Application.",
    ),
    "owners": (
        "pctl.azure.service_principals.owners:command",
        "List the owners of an Enterprise Application.",
    ),
    "add-owner": (
        "pctl.azure.service_principals.add_owner:command",
        "Add an owner, if it is not one already.",
    ),
    "remove-owner": (
        "pctl.azure.service_principals.remove_owner:command",
        "Remove an owner, if it is one.",
    ),
}


@click.group(name="sp", cls=PctlGroup, lazy_subcommands=LAZY_SUBCOMMANDS)
def service_principals() -> None:
    """Service principals, known in the portal as Enterprise Applications."""


__all__ = [
    "DEFAULT_LIST_COLUMNS",
    "MATCH_MODES",
    "OWNER_TYPES",
    "PRINCIPAL_MATCH_MODES",
    "collect_owners",
    "filter_by_principal",
    "label_roles",
    "looks_like_email",
    "looks_like_object_id",
    "match_option",
    "owner_label",
    "resolve_one",
    "resolve_owner",
    "resolve_owners",
    "service_principals",
]
