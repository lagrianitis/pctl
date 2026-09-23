"""Action: `pctl azure eam get-catalog`."""

from __future__ import annotations

import click

from ...options import azure_options, columns_option, output_options
from .common import CATALOG_COLUMNS, match_option
from .runner import run_get


@click.command(name="get-catalog")
@click.argument("identifier")
@azure_options
@match_option
@click.option("--select", metavar="FIELDS", help="Comma-separated Graph fields to request.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    identifier: str,
    match_mode: str,
    select: str | None,
) -> None:
    """Show catalogs matching a name, or one by object ID.

    As with get-package, prefix and contains are patterns and return every match. A
    single result is an object, several are an array.

    \b
      pctl azure eam get-catalog "AWS Platform"
      pctl azure eam get-catalog aws --match contains -o json
      pctl azure eam get-catalog AWS --match prefix -o ndjson
      pctl azure eam get-catalog d4f2d1b6-0a08-4987-9efd-fd8baae9e842
    """
    from ..graph import DEFAULT_CATALOG_SELECT

    run_get(
        ctx,
        collection="catalogs",
        noun="catalog",
        identifier=identifier,
        match_mode=match_mode,
        default_select=DEFAULT_CATALOG_SELECT,
        default_columns=CATALOG_COLUMNS,
        select=select,
    )
