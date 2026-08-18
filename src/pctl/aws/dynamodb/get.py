"""Action: `pctl aws ddb get`."""

from __future__ import annotations

from typing import Any

import click

from ...config import AppContext
from ...errors import NotFoundError
from ...options import aws_options, output_options
from ...output import Renderer, summarise


@click.command(name="get")
@click.argument("table")
@click.argument("key")
@aws_options
@click.option("--projection", metavar="EXPR", help="Fetch only these attributes.")
@click.option("--consistent", is_flag=True, help="Use a strongly consistent read.")
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    table: str,
    key: str,
    projection: str | None,
    consistent: bool,
) -> None:
    """Fetch a single item by primary key.

    KEY is JSON, either plain or DynamoDB-typed:

    \b
      pctl aws ddb get my-table '{"pk":"tenant#42","sk":"profile"}'
      pctl aws ddb get my-table '{"pk":{"S":"tenant#42"},"sk":{"S":"profile"}}'
    """
    from .client import get_item, make_client
    from .common import parse_json_option

    app = ctx.ensure_object(AppContext)
    parsed = parse_json_option(key, "KEY")
    if not parsed:
        raise click.BadParameter("key must be a non-empty JSON object", param_hint="KEY")

    extra: dict[str, Any] = {}
    if projection:
        extra["ProjectionExpression"] = projection
    if consistent:
        extra["ConsistentRead"] = True

    item = get_item(make_client(app.aws()), table, parsed, **extra)
    if item is None:
        raise NotFoundError(f"No item in {table} for key {key}")
    with Renderer(app.output, single=True) as renderer:
        renderer.write(item)
    summarise(1, "item", quiet=app.quiet)
