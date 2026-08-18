"""Action: `pctl azure groups get`."""

from __future__ import annotations

import asyncio
from typing import Any

import click

from ...config import AppContext
from ...errors import NotFoundError
from ...options import (
    azure_options,
    columns_option,
    output_options,
    read_names,
    split_columns,
)
from ...output import Renderer, summarise
from .. import graph_client
from .common import add_relations, match_option


@click.command(name="get")
@click.argument("names", nargs=-1)
@azure_options
@click.option(
    "-f",
    "--from-file",
    metavar="PATH",
    help="Read display names from a file, one per line ('-' for stdin).",
)
@match_option
@click.option("--members", is_flag=True, help="Include direct members.")
@click.option("--owners", is_flag=True, help="Include owners.")
@click.option("--transitive", is_flag=True, help="Include transitive (nested) members.")
@click.option("--counts", is_flag=True, help="Include member/owner counts without listing them.")
@click.option(
    "--member-limit",
    type=click.IntRange(min=1),
    help="Cap the number of members/owners fetched per group.",
)
@click.option("--select", metavar="FIELDS", help="Comma-separated Graph fields for the group.")
@click.option(
    "--ignore-missing",
    is_flag=True,
    help="Exit 0 even when a display name matches nothing.",
)
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    names: tuple[str, ...],
    from_file: str | None,
    match_mode: str,
    members: bool,
    owners: bool,
    transitive: bool,
    counts: bool,
    member_limit: int | None,
    select: str | None,
    ignore_missing: bool,
) -> None:
    """Show details for one or more groups, looked up by display name.

    Names can be positional or read from a file, and all of them are resolved
    concurrently.

    \b
      pctl azure groups get "AWS Platform Admins"
      pctl azure groups get "Team A" "Team B" --members --owners -o json
      pctl azure groups get -f groups.txt --counts -o csv
      pctl azure groups get platform --match search
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    wanted = read_names(names, from_file)
    if not wanted:
        raise click.UsageError("Provide at least one group display name, or use --from-file.")

    group_fields = split_columns(select)
    table_columns = app.columns or _columns(members, owners, transitive, counts)
    want_relations = members or owners or transitive or counts

    async def _run() -> tuple[list[dict[str, Any]], list[str]]:
        async with graph_client(app) as client:
            app.log(f"resolving {len(wanted)} display name(s) with match={match_mode}")
            resolved = await asyncio.gather(
                *[
                    client.find_groups_by_display_name(name, mode=match_mode, select=group_fields)
                    for name in wanted
                ]
            )

            found: list[dict[str, Any]] = []
            missing: list[str] = []
            for name, matches in zip(wanted, resolved, strict=True):
                if not matches:
                    missing.append(name)
                    continue
                for group in matches:
                    group["_query"] = name
                    found.append(group)

            if found and want_relations:
                app.log(f"fetching relations for {len(found)} group(s)")
                await asyncio.gather(
                    *[
                        add_relations(
                            client,
                            group,
                            members=members,
                            owners=owners,
                            transitive=transitive,
                            counts=counts,
                            member_limit=member_limit,
                        )
                        for group in found
                    ]
                )
            return found, missing

    found, missing = run(_run())

    with Renderer(app.output, columns=table_columns, single=len(found) == 1) as renderer:
        renderer.write_all(found)

    for name in missing:
        click.secho(f"No group matched display name: {name}", err=True, fg="yellow")
    summarise(len(found), "group", quiet=app.quiet)
    if missing and not ignore_missing:
        raise NotFoundError(
            f"{len(missing)} of {len(wanted)} display name(s) matched nothing. "
            "Try --match prefix or --match search."
        )


def _columns(members: bool, owners: bool, transitive: bool, counts: bool) -> list[str]:
    columns = ["displayName", "id", "mail"]
    if counts or members:
        columns.append("memberCount")
    if counts or owners:
        columns.append("ownerCount")
    if transitive:
        columns.append("transitiveMembers")
    return columns
