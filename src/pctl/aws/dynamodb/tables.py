"""Action: `pctl aws ddb tables`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...options import aws_options, output_options
from ...output import Renderer, summarise


@click.command(name="tables")
@aws_options
@output_options
@click.pass_context
def command(ctx: click.Context) -> None:
    """List the DynamoDB tables in this account and region.

    pctl aws ddb tables --profile tg-dev --region eu-central-1
    """
    from .client import list_tables, make_client

    app = ctx.ensure_object(AppContext)
    client = make_client(app.aws())
    with Renderer(app.output, columns=["table"]) as renderer:
        for name in list_tables(client):
            renderer.write({"table": name})
        count = renderer.count
    summarise(count, "table", quiet=app.quiet)
