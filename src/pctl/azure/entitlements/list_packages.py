"""Action: `pctl azure eam list-packages`."""

from __future__ import annotations

import click

from ...options import azure_options, columns_option, output_options
from .common import PACKAGE_COLUMNS, list_options
from .runner import run_list


@click.command(name="list-packages")
@azure_options
@click.option(
    "--catalog",
    metavar="NAME|ID",
    help="Only packages in this catalog. Takes a display name or an ID.",
)
@list_options
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    catalog: str | None,
    select: str | None,
    filter_expr: str | None,
    name: str | None,
    starts_with: str | None,
    contains: str | None,
    limit: int | None,
    page_size: int,
) -> None:
    """List access packages across every catalog you can read.

    --catalog scopes the result to one catalog and accepts its display name, resolving it
    to an ID for you. That costs one extra request, and a raw --filter takes precedence
    if you would rather write the OData yourself.

    Graph supports $filter and $select here but not $search or $count, so --contains
    filters locally after fetching. --name and --starts-with are server-side.

    \b
      pctl azure eam list-packages
      pctl azure eam list-packages --catalog "AWS Platform"
      pctl azure eam list-packages --catalog "AWS Platform" --starts-with "AWS "
      pctl azure eam list-packages --contains incident -o json
      pctl azure eam list-packages --filter "isHidden eq false" -o ndjson
    """
    from ..graph import DEFAULT_ACCESS_PACKAGE_SELECT

    run_list(
        ctx,
        collection="accessPackages",
        noun="access package",
        default_select=DEFAULT_ACCESS_PACKAGE_SELECT,
        default_columns=PACKAGE_COLUMNS,
        select=select,
        filter_expr=filter_expr,
        name=name,
        starts_with=starts_with,
        contains=contains,
        limit=limit,
        page_size=page_size,
        catalog=catalog,
    )
