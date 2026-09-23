"""Action: `pctl azure groups list`."""

from __future__ import annotations

import click

from ...config import GRAPH_MAX_PAGE_SIZE, AppContext
from ...options import azure_options, columns_option, output_options, split_columns
from ...output import Renderer, summarise
from .. import graph_client
from .common import DEFAULT_LIST_COLUMNS


@click.command(name="list")
@azure_options
@click.option(
    "--select",
    metavar="FIELDS",
    help="Comma-separated Graph fields to request. Fewer fields is faster.",
)
@click.option("--filter", "filter_expr", metavar="ODATA", help="Raw OData $filter expression.")
@click.option("--search", metavar="TEXT", help="Full-text search on displayName (substring).")
@click.option(
    "--starts-with",
    metavar="PREFIX",
    help="Shortcut for a startswith(displayName) filter.",
)
@click.option("--order-by", metavar="FIELD", help="Server-side ordering, e.g. displayName.")
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N groups.")
@click.option(
    "--page-size",
    type=click.IntRange(1, GRAPH_MAX_PAGE_SIZE),
    default=GRAPH_MAX_PAGE_SIZE,
    show_default=True,
    help="Graph $top page size.",
)
@click.option("--count-only", is_flag=True, help="Print just the total count.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    select: str | None,
    filter_expr: str | None,
    search: str | None,
    starts_with: str | None,
    order_by: str | None,
    limit: int | None,
    page_size: int,
    count_only: bool,
) -> None:
    """List every group in the tenant, following Graph pagination.

    The next page is fetched while the current one is still being written, so large
    tenants stream out at close to network speed.

    \b
      pctl azure groups list
      pctl azure groups list -o ndjson > groups.ndjson
      pctl azure groups list --starts-with "aws-" --limit 50
      pctl azure groups list --count-only
    """
    from ..graph import DEFAULT_GROUP_SELECT, escape_odata, run

    app = ctx.ensure_object(AppContext)
    if starts_with and not filter_expr:
        filter_expr = f"startswith(displayName,'{escape_odata(starts_with)}')"

    fields = split_columns(select) or list(DEFAULT_GROUP_SELECT)
    table_columns = app.columns or (fields if select else DEFAULT_LIST_COLUMNS)

    async def _run() -> int:
        async with graph_client(app) as client:
            if count_only:
                click.echo(await client.count_groups(filter_expr=filter_expr))
                return -1
            renderer = Renderer(app.output, columns=table_columns)
            async for group in client.list_groups(
                select=fields,
                filter_expr=filter_expr,
                search=search,
                order_by=order_by,
                limit=limit,
                page_size=page_size,
            ):
                renderer.write(group)
            return renderer.close()

    written = run(_run())
    if written >= 0:
        summarise(written, "group", quiet=app.quiet)
