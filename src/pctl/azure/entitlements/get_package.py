"""Action: `pctl azure eam get-package`."""

from __future__ import annotations

import click

from ...options import azure_options, columns_option, output_options
from .common import match_option
from .runner import run_get


@click.command(name="get-package")
@click.argument("identifier")
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
    """Show an access package, by display name or object ID.

    --match is exact by default. `prefix` is server-side; `contains` fetches the
    collection and filters locally, because Graph offers no substring operator here.

    --with-policies expands assignmentPolicies, which is where the approval and
    expiry rules live. Without it you get the package alone.

    \b
      pctl azure eam get-package "AWS Platform Access"
      pctl azure eam get-package incident --match contains
      pctl azure eam get-package "AWS Platform Access" --with-policies -o json
      pctl azure eam get-package a914b616-e04e-476b-aa37-91038f0b165b
    """
    from ..graph import DEFAULT_ACCESS_PACKAGE_SELECT

    run_get(
        ctx,
        collection="accessPackages",
        noun="access package",
        identifier=identifier,
        match_mode=match_mode,
        default_select=DEFAULT_ACCESS_PACKAGE_SELECT,
        select=select,
        expand=("assignmentPolicies",) if with_policies else None,
    )
