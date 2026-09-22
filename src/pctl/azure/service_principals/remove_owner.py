"""Action: `pctl azure sp remove-owner`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...options import azure_options, output_options
from ...output import Renderer
from .. import graph_client
from .common import OWNER_TYPES, match_option, owner_label, resolve_one, resolve_owner

# Microsoft's guidance is that a service principal should keep at least two owners, so
# that losing one person does not orphan the application.
RECOMMENDED_MINIMUM_OWNERS = 2


@click.command(name="remove-owner")
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
    """Remove an owner from an Enterprise Application, if it is one.

    OWNER is a display name or a directory object ID, resolved the same way as
    `add-owner`.

    Idempotent by design: the current owners are read first, and an owner that is not
    there is reported as information on exit 0 rather than an error.

    Requires Application.ReadWrite.All or Directory.ReadWrite.All. Warns when the
    removal would leave fewer than two owners, which is Microsoft's recommended
    minimum, but does not refuse.

    \b
      pctl azure sp remove-owner "Company Incident.io SCIM" "Ann Example"
      pctl azure sp remove-owner SCIM e6901838-637f-4bc7-b843-a8a7725a4872
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)

    async def _run() -> tuple[dict[str, str], bool, int]:
        async with graph_client(app) as client:
            target = await resolve_one(client, name, mode=match_mode)
            sp_id = target["id"]
            resolved = await resolve_owner(client, owner, mode=owner_match, owner_type=owner_type)
            app.log(f"removing {owner_label(resolved)} from {target.get('displayName')} ({sp_id})")

            existing = [item["id"] async for item in client.owners(sp_id)]
            record = {
                "servicePrincipal": target.get("displayName") or sp_id,
                "servicePrincipalId": sp_id,
                "owner": resolved.get("displayName") or resolved["id"],
                "ownerId": resolved["id"],
            }
            if resolved["id"] not in existing:
                return {**record, "status": "not-an-owner"}, False, len(existing)
            await client.remove_owner(sp_id, resolved["id"])
            return {**record, "status": "removed"}, True, len(existing) - 1

    record, removed, remaining = run(_run())

    with Renderer(app.output, columns=list(record), single=True) as renderer:
        renderer.write(record)

    if not removed:
        click.secho(
            f"{record['owner']} is not an owner of {record['servicePrincipal']}; nothing to do.",
            err=True,
            fg="cyan",
        )
        return

    if not app.quiet:
        click.secho(
            f"Removed {record['owner']} from {record['servicePrincipal']}.",
            err=True,
            fg="green",
        )
    if remaining < RECOMMENDED_MINIMUM_OWNERS:
        click.secho(
            f"{record['servicePrincipal']} now has {remaining} owner(s). "
            f"Microsoft recommends at least {RECOMMENDED_MINIMUM_OWNERS}.",
            err=True,
            fg="yellow",
        )
