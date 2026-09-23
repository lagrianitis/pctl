"""The `eam` service under the `azure` case: Entra ID entitlement management.

Read-only. Access packages are bundles of resources governed by policies, and they live in
containers called catalogs, so both are exposed here.

These collections sit under `identityGovernance/entitlementManagement` and support a
narrower OData surface than the directory: `$select`, `$filter` and `$expand`, but not
`$search` or `$count`. That is why this service does not reuse the directory helpers, and
why its `--match contains` filters locally.

`__init__.py` declares the service group and its actions; shared code lives in
`common.py`, because a package namespace also receives its submodules as attributes and
would shadow builtins of the same name.
"""

from __future__ import annotations

import click

from ...lazy import PctlGroup
from .common import (
    ASSIGNMENT_COLUMNS,
    ASSIGNMENT_STATES,
    CATALOG_COLUMNS,
    MATCH_MODES,
    PACKAGE_COLUMNS,
    match_option,
)

# Verb-noun actions rather than a nested `packages list`: the command shape is
# case -> service -> action with no fourth level, and an action that silently switches
# between listing and getting depending on whether an argument was passed would be
# magic the rest of this CLI does not do.
LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "list-packages": (
        "pctl.azure.entitlements.list_packages:command",
        "List access packages in the tenant.",
    ),
    "get-package": (
        "pctl.azure.entitlements.get_package:command",
        "Show an access package by name or ID.",
    ),
    "delete-package": (
        "pctl.azure.entitlements.delete_package:command",
        "Delete an access package. Irreversible.",
    ),
    "list-catalogs": (
        "pctl.azure.entitlements.list_catalogs:command",
        "List access package catalogs.",
    ),
    "get-catalog": (
        "pctl.azure.entitlements.get_catalog:command",
        "Show a catalog by name or ID.",
    ),
    "list-assignments": (
        "pctl.azure.entitlements.list_assignments:command",
        "List who is assigned to an access package.",
    ),
    "add-assignment": (
        "pctl.azure.entitlements.add_assignment:command",
        "Assign people to an access package, by email.",
    ),
    "remove-assignment": (
        "pctl.azure.entitlements.remove_assignment:command",
        "Remove people's assignment to an access package.",
    ),
    "get-request": (
        "pctl.azure.entitlements.get_request:command",
        "Show an assignment request, to see whether a write landed.",
    ),
}


@click.group(name="eam", cls=PctlGroup, lazy_subcommands=LAZY_SUBCOMMANDS)
def entitlements() -> None:
    """Entitlement management: access packages and their catalogs."""


__all__ = [
    "ASSIGNMENT_COLUMNS",
    "ASSIGNMENT_STATES",
    "CATALOG_COLUMNS",
    "MATCH_MODES",
    "PACKAGE_COLUMNS",
    "entitlements",
    "match_option",
]
