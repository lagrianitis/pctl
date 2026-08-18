"""Action: `pctl aws ddb scan`."""

from __future__ import annotations

import os

import click

from ...config import AppContext
from ...options import aws_options, columns_option, output_options
from ...output import Renderer, summarise
from .client import MAX_SEGMENTS
from .common import read_options


@click.command(name="scan")
@click.argument("table")
@aws_options
@read_options
@click.option(
    "--segments",
    type=click.IntRange(1, MAX_SEGMENTS),
    default=None,
    help=f"Parallel scan segments, 1-{MAX_SEGMENTS}.  [default: CPU count, max 8]",
)
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    table: str,
    index: str | None,
    projection: str | None,
    expression_values: str | None,
    expression_names: str | None,
    filter_expression: str | None,
    limit: int | None,
    segments: int | None,
    page_size: int | None,
    consistent: bool,
) -> None:
    """Scan a table, streaming items as they arrive.

    A scan reads the whole table, so it costs read capacity proportional to the
    table's size. Narrow the payload with --projection and spread the work across
    threads with --segments.

    \b
      pctl aws ddb scan my-table -n 20
      pctl aws ddb scan my-table --segments 8 -o ndjson > items.ndjson
      pctl aws ddb scan my-table --filter "#s = :s" \\
          --names '{"#s":"status"}' --values '{":s":"ACTIVE"}'
    """
    from .client import ScanRequest, make_client, scan, serialize_values
    from .common import parse_json_option

    app = ctx.ensure_object(AppContext)
    if segments is None:
        # One segment is usually network-bound, so a few threads help. Too many
        # just burn read capacity. With --limit, one segment avoids overfetching.
        segments = 1 if limit else min(8, os.cpu_count() or 2)

    request = ScanRequest(
        table=table,
        index=index,
        projection=projection,
        filter_expression=filter_expression,
        expression_values=serialize_values(parse_json_option(expression_values, "--values")),
        expression_names=parse_json_option(expression_names, "--names"),
        consistent=consistent,
        page_size=page_size,
        limit=limit,
        segments=segments,
    )
    client = make_client(app.aws(), max_pool=segments + 4)
    with Renderer(app.output, columns=app.columns) as renderer:
        for item in scan(client, request, log=app.log if app.verbose else None):
            renderer.write(item)
        count = renderer.count
    summarise(count, "item", quiet=app.quiet)
