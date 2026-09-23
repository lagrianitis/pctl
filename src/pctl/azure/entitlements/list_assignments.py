"""Action: `pctl azure eam list-assignments`."""

from __future__ import annotations

import click

from ...config import GRAPH_MAX_PAGE_SIZE, AppContext
from ...options import azure_options, columns_option, output_options, split_columns
from ...output import Renderer, summarise
from .. import graph_client
from .common import (
    ASSIGNMENT_COLUMNS,
    ASSIGNMENT_STATES,
    contains_filter,
    flatten_assignment,
    resolve_package_id,
)

# target and accessPackage are relationships, so without expanding them an assignment is
# two GUIDs and a state: true but unreadable.
DEFAULT_EXPAND = ("target", "accessPackage")


@click.command(name="list-assignments")
@azure_options
@click.option(
    "--access-package",
    "package",
    metavar="NAME|ID",
    help="Only assignments to this access package. Takes a display name or an ID.",
)
@click.option(
    "--state",
    type=click.Choice(ASSIGNMENT_STATES),
    help="Only assignments in this state. Delivered means access is live.",
)
@click.option("--filter", "filter_expr", metavar="ODATA", help="Raw OData $filter expression.")
@click.option(
    "--target",
    metavar="TEXT",
    help="Keep assignments whose target name or email contains TEXT. Filtered locally.",
)
@click.option(
    "--no-expand",
    is_flag=True,
    help="Skip expanding target and accessPackage, leaving the raw relationship IDs.",
)
@click.option("--select", metavar="FIELDS", help="Comma-separated Graph fields to request.")
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N assignments.")
@click.option(
    "--page-size",
    type=click.IntRange(1, GRAPH_MAX_PAGE_SIZE),
    default=GRAPH_MAX_PAGE_SIZE,
    show_default=True,
    help="Graph $top page size.",
)
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    package: str | None,
    state: str | None,
    filter_expr: str | None,
    target: str | None,
    no_expand: bool,
    select: str | None,
    limit: int | None,
    page_size: int,
) -> None:
    """List who is assigned to an access package.

    --access-package takes a display name and resolves it to the ID the filter needs, so
    you do not have to look it up first. Combine it with --state Delivered to see only
    live access, which is the usual question.

    target and accessPackage are expanded by default, and their names lifted to
    targetDisplayName, targetEmail and accessPackageName so a table or CSV can address
    them. The nested objects stay intact for json and ndjson.

    --target filters locally on the expanded name and email, because Graph does not
    support a substring operator on these collections.

    \b
      pctl azure eam list-assignments --access-package "AWS Platform Access"
      pctl azure eam list-assignments --access-package "AWS Platform Access" --state Delivered
      pctl azure eam list-assignments --state Expired -o ndjson
      pctl azure eam list-assignments --access-package "AWS Platform Access" --target ann@
      pctl azure eam list-assignments --filter "state eq 'Delivered'" -o json
    """
    from ..graph import escape_odata, run

    app = ctx.ensure_object(AppContext)
    fields = split_columns(select)
    columns = app.columns or (fields if select else ASSIGNMENT_COLUMNS)
    expand = None if no_expand else DEFAULT_EXPAND

    async def _run() -> int:
        async with graph_client(app) as client:
            clauses: list[str] = []
            if filter_expr:
                clauses.append(filter_expr)
            else:
                if package:
                    resolved = await resolve_package_id(client, package)
                    clauses.append(f"accessPackage/id eq '{resolved}'")
                if state:
                    clauses.append(f"state eq '{escape_odata(state)}'")
            server_filter = " and ".join(clauses) or None
            app.log(f"listing assignments filter={server_filter or 'none'}")

            stream = client.list_governance(
                "assignments",
                select=fields,
                filter_expr=server_filter,
                expand=expand,
                limit=None if target else limit,
                page_size=page_size,
            )

            if target:
                # The local filter reads the expanded names, so flattening comes first.
                items = [flatten_assignment(item) async for item in stream]
                matched = _matching_target(items, target)
                if limit is not None:
                    matched = matched[:limit]
                with Renderer(app.output, columns=columns) as renderer:
                    renderer.write_all(matched)
                return len(matched)

            renderer = Renderer(app.output, columns=columns)
            async for item in stream:
                renderer.write(flatten_assignment(item))
            return renderer.close()

    summarise(run(_run()), "assignment", quiet=app.quiet)


def _matching_target(items: list[dict[str, object]], needle: str) -> list[dict[str, object]]:
    """Assignments whose target display name or email contains the needle.

    Both fields are checked because a person is as likely to be looked up by address as by
    name, and the caller should not have to know which one this tenant fills in.
    """
    by_name = contains_filter(items, needle)
    wanted = needle.casefold()
    by_email = [
        item
        for item in items
        if wanted in str(item.get("targetEmail") or "").casefold() and item not in by_name
    ]
    return [*by_name, *by_email]
