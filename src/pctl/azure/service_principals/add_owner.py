"""Action: `pctl azure sp add-owner`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...options import azure_options, output_options
from ...output import Renderer
from .. import graph_client
from .common import OWNER_TYPES, match_option, owner_label, resolve_one, resolve_owner


@click.command(name="add-owner")
@click.argument("name")
@click.argument("owner")
@azure_options
@match_option
@click.option(
    "--owner-type",
    type=click.Choice(OWNER_TYPES),
    default="auto",
    show_default=True,
    help="Where to look up the owner name: users, service principals, or both.",
)
@click.option(
    "--owner-match",
    type=click.Choice(["exact", "prefix", "search"]),
    default="exact",
    show_default=True,
    help="How to match the owner display name. Exact, so a write cannot hit the wrong object.",
)
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    name: str,
    owner: str,
    match_mode: str,
    owner_type: str,
    owner_match: str,
) -> None:
    """Add an owner to an Enterprise Application, if it is not one already.

    OWNER is a display name or a directory object ID. A GUID is used as-is; anything else
    is resolved against users and then service principals, which are the only object
    types that can own a service principal.

    Idempotent by design: the current owners are read first, and an existing owner is
    reported as information on exit 0 rather than an error, so this is safe to re-run
    from a script or a pipeline.

    Requires Application.ReadWrite.All or Directory.ReadWrite.All. Owner resolution is
    exact by default, because a prefix match on a write could name the wrong person.

    \b
      pctl azure sp add-owner "Company Incident.io SCIM" "Ann Example"
      pctl azure sp add-owner SCIM e6901838-637f-4bc7-b843-a8a7725a4872
      pctl azure sp add-owner SCIM "platform-automation" --owner-type sp
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)

    async def _run() -> tuple[dict[str, str], bool]:
        async with graph_client(app) as client:
            target = await resolve_one(client, name, mode=match_mode)
            sp_id = target["id"]
            resolved = await resolve_owner(client, owner, mode=owner_match, owner_type=owner_type)
            app.log(f"adding {owner_label(resolved)} to {target.get('displayName')} ({sp_id})")

            existing = {item["id"] async for item in client.owners(sp_id)}
            record = {
                "servicePrincipal": target.get("displayName") or sp_id,
                "servicePrincipalId": sp_id,
                "owner": resolved.get("displayName") or resolved["id"],
                "ownerId": resolved["id"],
            }
            if resolved["id"] in existing:
                return {**record, "status": "already-owner"}, False
            await client.add_owner(sp_id, resolved["id"])
            return {**record, "status": "added"}, True

    record, added = run(_run())

    with Renderer(app.output, columns=list(record), single=True) as renderer:
        renderer.write(record)

    if not added:
        click.secho(
            f"{record['owner']} is already an owner of {record['servicePrincipal']}; "
            "nothing to do.",
            err=True,
            fg="cyan",
        )
    elif not app.quiet:
        click.secho(
            f"Added {record['owner']} as an owner of {record['servicePrincipal']}.",
            err=True,
            fg="green",
        )
