"""Action: `pctl aws ddb query`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...options import aws_options, columns_option, output_options
from ...output import Renderer, summarise
from .common import read_options


@click.command(name="query")
@click.argument("table")
@aws_options
@read_options
@click.option(
    "--key",
    "key_condition",
    metavar="EXPR",
    required=True,
    help='KeyConditionExpression, e.g. "pk = :pk AND begins_with(sk, :prefix)".',
)
@click.option("--desc", "descending", is_flag=True, help="Return items in descending sort order.")
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
    key_condition: str,
    filter_expression: str | None,
    limit: int | None,
    page_size: int | None,
    descending: bool,
    consistent: bool,
) -> None:
    """Query a table or index by key condition.

    Prefer query over scan whenever the partition key is known.

    \b
      pctl aws ddb query my-table --key "pk = :pk" --values '{":pk":"tenant#42"}'
      pctl aws ddb query my-table --index gsi1 --key "gsi1pk = :p" \\
          --values '{":p":"ACTIVE"}' --desc -n 10
    """
    from .client import ScanRequest, make_client, query, serialize_values
    from .common import parse_json_option

    app = ctx.ensure_object(AppContext)
    request = ScanRequest(
        table=table,
        index=index,
        projection=projection,
        filter_expression=filter_expression,
        key_condition=key_condition,
        expression_values=serialize_values(parse_json_option(expression_values, "--values")),
        expression_names=parse_json_option(expression_names, "--names"),
        consistent=consistent,
        page_size=page_size,
        limit=limit,
        descending=descending,
    )
    client = make_client(app.aws())
    with Renderer(app.output, columns=app.columns) as renderer:
        for item in query(client, request, log=app.log if app.verbose else None):
            renderer.write(item)
        count = renderer.count
    summarise(count, "item", quiet=app.quiet)
