"""Action: `pctl azure sp owners`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...options import azure_options, columns_option, output_options
from ...output import Renderer, summarise
from .. import graph_client
from .common import match_option, resolve_one


@click.command(name="owners")
@click.argument("name")
@azure_options
@match_option
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N owners.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    name: str,
    match_mode: str,
    limit: int | None,
) -> None:
    """List the owners of an Enterprise Application.

    Owners are users or other service principals, never groups, so the result is a mixed
    collection of directory objects. `@odata.type` distinguishes them, and is included in
    the JSON output.

    \b
      pctl azure sp owners "Company Incident.io SCIM"
      pctl azure sp owners "Company Incident.io SCIM" -o json
      pctl azure sp owners SCIM -o ndjson | jq -r .displayName
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    columns = app.columns or ["displayName", "userPrincipalName", "id"]

    async def _run() -> int:
        async with graph_client(app) as client:
            target = await resolve_one(client, name, mode=match_mode)
            app.log(f"resolved '{name}' to {target.get('displayName')} ({target['id']})")
            renderer = Renderer(app.output, columns=columns)
            async for owner in client.owners(target["id"], limit=limit):
                renderer.write(owner)
            return renderer.close()

    summarise(run(_run()), "owner", quiet=app.quiet)
