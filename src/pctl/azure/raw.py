"""Action: `pctl azure raw`. An escape hatch for any Graph path."""

from __future__ import annotations

from typing import Any

import click

from ..config import AppContext
from ..options import azure_options, columns_option, output_options
from ..output import Renderer, dumps, summarise
from . import graph_client


@click.command(name="raw")
@click.argument("path")
@azure_options
@click.option("--param", "params", multiple=True, metavar="KEY=VALUE", help="Query parameter.")
@click.option("--paginate/--no-paginate", default=True, help="Follow @odata.nextLink.")
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N items.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    path: str,
    params: tuple[str, ...],
    paginate: bool,
    limit: int | None,
) -> None:
    """Call any Graph path, with auth, retries and pagination handled.

    \b
      pctl azure raw users --param '$select=id,displayName' -n 10
      pctl azure raw organization --no-paginate
    """
    from .graph import run

    app = ctx.ensure_object(AppContext)
    query: dict[str, Any] = {}
    for item in params:
        key, sep, value = item.partition("=")
        if not sep:
            raise click.BadParameter(f"expected KEY=VALUE, got {item!r}", param_hint="--param")
        query[key] = value

    async def _run() -> int:
        async with graph_client(app) as client:
            if not paginate:
                payload = await client.get_json(path, params=query or None)
                click.echo(dumps(payload, indent=True).decode())
                return -1
            renderer = Renderer(app.output, columns=app.columns)
            async for item in client.paginate(path, params=query or None, limit=limit):
                renderer.write(item)
            return renderer.close()

    written = run(_run())
    if written >= 0:
        summarise(written, "item", quiet=app.quiet)
