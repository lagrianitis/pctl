"""Action: `pctl azure groups members`."""

from __future__ import annotations

import click

from ...config import GRAPH_MAX_PAGE_SIZE, AppContext
from ...options import azure_options, columns_option, output_options
from ...output import Renderer, summarise
from .. import graph_client
from .common import DEFAULT_MEMBER_COLUMNS, match_option, resolve_one


@click.command(name="members")
@click.argument("name")
@azure_options
@match_option
@click.option("--owners", is_flag=True, help="List owners instead of members.")
@click.option("--transitive", is_flag=True, help="Include nested group members.")
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N results.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    name: str,
    match_mode: str,
    owners: bool,
    transitive: bool,
    limit: int | None,
) -> None:
    """Stream the members (or owners) of a single group, resolved by display name.

    \b
      pctl azure groups members "AWS Platform Admins" -o csv
      pctl azure groups members "AWS Platform Admins" --owners
      pctl azure groups members "AWS Platform Admins" --transitive -o ndjson
    """
    from ..graph import DEFAULT_MEMBER_SELECT, run

    app = ctx.ensure_object(AppContext)
    relation = "members"
    if owners:
        relation = "owners"
    elif transitive:
        relation = "transitiveMembers"
    table_columns = app.columns or DEFAULT_MEMBER_COLUMNS

    async def _run() -> int:
        async with graph_client(app) as client:
            group = await resolve_one(client, name, mode=match_mode)
            renderer = Renderer(app.output, columns=table_columns)
            params = {"$top": GRAPH_MAX_PAGE_SIZE, "$select": ",".join(DEFAULT_MEMBER_SELECT)}
            async for member in client.paginate(
                f"groups/{group['id']}/{relation}", params=params, limit=limit
            ):
                renderer.write(member)
            return renderer.close()

    written = run(_run())
    summarise(written, "owner" if owners else "member", quiet=app.quiet)
