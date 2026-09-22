"""Action: `pctl azure sp assignments`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...errors import NotFoundError
from ...options import azure_options, columns_option, output_options
from ...output import Renderer, summarise
from .. import graph_client
from .common import filter_by_principal, label_roles, match_option, resolve_one


@click.command(name="assignments")
@click.argument("name")
@azure_options
@match_option
@click.option(
    "--principal",
    metavar="NAME",
    help="Only assignments whose principalDisplayName matches exactly (case-insensitive).",
)
@click.option(
    "--outbound",
    is_flag=True,
    help="Invert the direction: what this service principal is assigned to.",
)
@click.option(
    "--no-role-names",
    is_flag=True,
    help="Skip the extra request that resolves appRoleId to a role name.",
)
@click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N assignments.")
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    name: str,
    match_mode: str,
    principal: str | None,
    outbound: bool,
    no_role_names: bool,
    limit: int | None,
) -> None:
    """List app role assignments for an Enterprise Application.

    By default this answers "who has access to this app": the principals assigned to
    it, via `appRoleAssignedTo`. Use --outbound for the reverse question, what the
    service principal itself is assigned to.

    Each assignment gains an `appRoleName`, resolved from the roles the application
    exposes, because `appRoleId` on its own is an opaque GUID. The all-zero GUID means
    Default Access, which is what an app without its own roles assigns.

    --principal filters client-side, since Graph does not support $filter on
    principalDisplayName for this relation.

    \b
      pctl azure sp assignments "Company Incident.io SCIM"
      pctl azure sp assignments "Company Incident.io SCIM" -o ndjson
      pctl azure sp assignments "Company Incident.io SCIM" --principal "AWS Platform Admins"
      pctl azure sp assignments "Company Incident.io SCIM" --outbound -o json
    """
    from ..graph import DEFAULT_ASSIGNMENT_COLUMNS, run

    app = ctx.ensure_object(AppContext)
    columns = app.columns or [
        *DEFAULT_ASSIGNMENT_COLUMNS[:2],
        "appRoleName",
        *DEFAULT_ASSIGNMENT_COLUMNS[2:],
    ]
    if no_role_names:
        columns = [column for column in columns if column != "appRoleName"]

    async def _run() -> list[dict[str, str]]:
        async with graph_client(app) as client:
            target = await resolve_one(client, name, mode=match_mode)
            sp_id = target["id"]
            app.log(f"resolved '{name}' to {target.get('displayName')} ({sp_id})")

            items = await client.app_role_assignments(sp_id, outbound=outbound, limit=limit)
            if not no_role_names and items:
                label_roles(items, await client.app_role_names(sp_id))
            return filter_by_principal(items, principal)

    found = run(_run())

    with Renderer(app.output, columns=columns) as renderer:
        renderer.write_all(found)

    summarise(len(found), "assignment", quiet=app.quiet)
    if principal and not found:
        raise NotFoundError(f"No assignment on '{name}' for principal: {principal}")
