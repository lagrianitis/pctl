"""Action: `pctl azure eam get-package`."""

from __future__ import annotations

import click

from ...options import azure_options, columns_option, output_options
from .common import PACKAGE_COLUMNS, match_option
from .runner import run_get


@click.command(name="get-package")
@click.option(
    "--access-package",
    "identifier",
    required=True,
    metavar="NAME|ID",
    help="Display name, name pattern, or object ID.",
)
@azure_options
@match_option
@click.option(
    "--with-policies",
    is_flag=True,
    help="Expand the assignment policies that govern the package.",
)
@click.option("--select", metavar="FIELDS", help="Comma-separated Graph fields to request.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    identifier: str,
    match_mode: str,
    with_policies: bool,
    select: str | None,
) -> None:
    """Show access packages matching a name, or one by object ID.

    --match exact (the default) and prefix are server-side; contains fetches the
    collection and filters locally, because Graph offers no substring operator here.

    prefix and contains are patterns, so they return every match rather than refusing an
    ambiguous one. A single result is emitted as an object and several as an array, the
    same shape `groups get` uses, so jq needs no index for the common case.

    --with-policies expands assignmentPolicies, where the approval and expiry rules live.

    \b
      pctl azure eam get-package --access-package "AWS Platform Access"
      pctl azure eam get-package --access-package AWS --match prefix -o ndjson
      pctl azure eam get-package --access-package incident --match contains
      pctl azure eam get-package --access-package "AWS Platform Access" --with-policies
      pctl azure eam get-package --access-package a914b616-e04e-476b-aa37-91038f0b165b
    """
    from ..graph import DEFAULT_ACCESS_PACKAGE_SELECT

    run_get(
        ctx,
        collection="accessPackages",
        noun="access package",
        identifier=identifier,
        match_mode=match_mode,
        default_select=DEFAULT_ACCESS_PACKAGE_SELECT,
        default_columns=PACKAGE_COLUMNS,
        select=select,
        expand=("assignmentPolicies",) if with_policies else None,
    )
