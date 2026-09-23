"""Action: `pctl azure eam list-catalogs`."""

from __future__ import annotations

import click

from ...options import azure_options, columns_option, output_options
from .common import CATALOG_COLUMNS, list_options
from .runner import run_list


@click.command(name="list-catalogs")
@azure_options
@list_options
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    select: str | None,
    filter_expr: str | None,
    name: str | None,
    starts_with: str | None,
    contains: str | None,
    limit: int | None,
    page_size: int,
) -> None:
    """List access package catalogs.

    A catalog is the container an access package lives in, so this is usually the first
    call when exploring entitlement management in an unfamiliar tenant.

    \b
      pctl azure eam list-catalogs
      pctl azure eam list-catalogs --contains aws -o json
      pctl azure eam list-catalogs --filter "state eq 'published'"
    """
    from ..graph import DEFAULT_CATALOG_SELECT

    run_list(
        ctx,
        collection="catalogs",
        noun="catalog",
        default_select=DEFAULT_CATALOG_SELECT,
        default_columns=CATALOG_COLUMNS,
        select=select,
        filter_expr=filter_expr,
        name=name,
        starts_with=starts_with,
        contains=contains,
        limit=limit,
        page_size=page_size,
    )
