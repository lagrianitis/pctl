"""Action: `pctl azure sp get`."""

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
from .common import match_option


@click.command(name="get")
@click.option(
    "--name",
    "names",
    multiple=True,
    metavar="NAME",
    help="Service principal display name. Repeat for several.",
)
@azure_options
@click.option(
    "-f",
    "--from-file",
    metavar="PATH",
    help="Read display names from a file, one per line ('-' for stdin).",
)
@match_option
@click.option(
    "--assignments",
    is_flag=True,
    help="Include who is assigned to the app (appRoleAssignedTo).",
)
@click.option(
    "--roles",
    is_flag=True,
    help="Include the app roles the application exposes.",
)
@click.option(
    "--assignment-limit",
    type=click.IntRange(min=1),
    help="Cap the number of assignments fetched per service principal.",
)
@click.option(
    "--select", metavar="FIELDS", help="Comma-separated Graph fields to request."
)
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
    assignments: bool,
    roles: bool,
    assignment_limit: int | None,
    select: str | None,
    ignore_missing: bool,
) -> None:
    """Show details for one or more service principals, by display name.

    `--match search` is the default here, because Enterprise Application names are
    long and rarely typed exactly. It is the Graph full-text search, so it matches
    substrings.

    \b
      pctl azure sp get --name "Company Incident.io SCIM"
      pctl azure sp get --name "incident.io" -o json
      pctl azure sp get --name "Company Incident.io SCIM" --assignments -o ndjson
      pctl azure sp get --name "Company Incident.io SCIM" --roles -o json
      pctl azure sp get -f apps.txt --match exact
    """
    from ..graph import DEFAULT_SERVICE_PRINCIPAL_SELECT, run

    app = ctx.ensure_object(AppContext)
    wanted = read_names(names, from_file)
    if not wanted:
        raise click.UsageError(
            "Provide at least one service principal display name with --name, or use --from-file."
        )

    fields = split_columns(select) or [*DEFAULT_SERVICE_PRINCIPAL_SELECT]
    if roles and "appRoles" not in fields:
        fields = [*fields, "appRoles"]
    table_columns = app.columns or _columns(assignments)

    async def _run() -> tuple[list[dict[str, Any]], list[str]]:
        async with graph_client(app) as client:
            app.log(f"resolving {len(wanted)} display name(s) with match={match_mode}")
            resolved = await asyncio.gather(
                *[
                    client.find_service_principals_by_display_name(
                        name, mode=match_mode, select=fields
                    )
                    for name in wanted
                ]
            )

            found: list[dict[str, Any]] = []
            missing: list[str] = []
            for name, matches in zip(wanted, resolved, strict=True):
                if not matches:
                    missing.append(name)
                    continue
                for item in matches:
                    item["_query"] = name
                    found.append(item)

            if found and assignments:
                app.log(f"fetching assignments for {len(found)} service principal(s)")
                collected = await asyncio.gather(
                    *[
                        client.app_role_assignments(item["id"], limit=assignment_limit)
                        for item in found
                        if item.get("id")
                    ]
                )
                for item, items in zip(
                    [found_item for found_item in found if found_item.get("id")],
                    collected,
                    strict=True,
                ):
                    item["appRoleAssignedTo"] = items
                    item["assignmentCount"] = len(items)
            return found, missing

    found, missing = run(_run())

    with Renderer(
        app.output, columns=table_columns, single=len(found) == 1
    ) as renderer:
        renderer.write_all(found)

    for name in missing:
        click.secho(
            f"No service principal matched display name: {name}", err=True, fg="yellow"
        )
    summarise(len(found), "service principal", quiet=app.quiet)
    if missing and not ignore_missing:
        raise NotFoundError(
            f"{len(missing)} of {len(wanted)} display name(s) matched nothing. "
            "Try --match prefix, or a shorter --match search term."
        )


def _columns(assignments: bool) -> list[str]:
    columns = ["displayName", "appId", "servicePrincipalType", "accountEnabled", "id"]
    if assignments:
        columns.append("assignmentCount")
    return columns
