"""Action: `pctl azure sp list`."""

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
@click.option(
    "--filter", "filter_expr", metavar="ODATA", help="Raw OData $filter expression."
)
@click.option(
    "--search", metavar="TEXT", help="Full-text search on displayName (substring)."
)
@click.option(
    "--starts-with",
    metavar="PREFIX",
    help="Shortcut for a startswith(displayName) filter.",
)
@click.option(
    "--app-id",
    metavar="GUID",
    help="Find the service principal for an application (client) ID.",
)
@click.option(
    "--order-by", metavar="FIELD", help="Server-side ordering, e.g. displayName."
)
@click.option(
    "-n", "--limit", type=click.IntRange(min=1), help="Stop after N service principals."
)
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
    app_id: str | None,
    order_by: str | None,
    limit: int | None,
    page_size: int,
    count_only: bool,
) -> None:
    """List service principals, following Graph pagination.

    A tenant typically has hundreds of these, most of them Microsoft first-party
    apps, so narrow the result server-side rather than filtering afterwards.

    \b
      pctl azure sp list --search "incident.io"
      pctl azure sp list --starts-with "Company " -o ndjson
      pctl azure sp list --app-id 00000003-0000-0000-c000-000000000000
      pctl azure sp list --filter "accountEnabled eq true" --count-only
    """
    from ..graph import DEFAULT_SERVICE_PRINCIPAL_SELECT, escape_odata, run

    app = ctx.ensure_object(AppContext)
    if app_id and not filter_expr:
        filter_expr = f"appId eq '{escape_odata(app_id)}'"
    elif starts_with and not filter_expr:
        filter_expr = f"startswith(displayName,'{escape_odata(starts_with)}')"

    fields = split_columns(select) or list(DEFAULT_SERVICE_PRINCIPAL_SELECT)
    table_columns = app.columns or (fields if select else DEFAULT_LIST_COLUMNS)

    async def _run() -> int:
        async with graph_client(app) as client:
            if count_only:
                click.echo(
                    await client.count_service_principals(filter_expr=filter_expr)
                )
                return -1
            renderer = Renderer(app.output, columns=table_columns)
            async for item in client.list_service_principals(
                select=fields,
                filter_expr=filter_expr,
                search=search,
                order_by=order_by,
                limit=limit,
                page_size=page_size,
            ):
                renderer.write(item)
            return renderer.close()

    written = run(_run())
    if written >= 0:
        summarise(written, "service principal", quiet=app.quiet)
