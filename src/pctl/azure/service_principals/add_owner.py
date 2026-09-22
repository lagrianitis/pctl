"""Action: `pctl azure sp add-owner`."""

from __future__ import annotations

import asyncio
from typing import Any

import click

from ...config import AppContext
from ...errors import NotFoundError
from ...options import azure_options, output_options
from ...output import Renderer, summarise
from .. import graph_client
from .common import (
    OWNER_TYPES,
    collect_owners,
    match_option,
    resolve_one,
    resolve_owners,
)


@click.command(name="add-owner")
@click.argument("name")
@click.argument("owners", nargs=-1)
@azure_options
@match_option
@click.option(
    "--emails",
    metavar="A@B,C@D",
    help="Comma-separated owner addresses, added to any given positionally.",
)
@click.option(
    "--owner-type",
    type=click.Choice(OWNER_TYPES),
    default="auto",
    show_default=True,
    help="Where to look up an owner name: users, service principals, or both.",
)
@click.option(
    "--owner-match",
    type=click.Choice(["exact", "prefix", "search"]),
    default="exact",
    show_default=True,
    help="How to match an owner display name. Exact, so a write cannot hit the wrong object.",
)
@click.option(
    "--ignore-missing",
    is_flag=True,
    help="Exit 0 even when an owner could not be resolved.",
)
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    name: str,
    owners: tuple[str, ...],
    match_mode: str,
    emails: str | None,
    owner_type: str,
    owner_match: str,
    ignore_missing: bool,
) -> None:
    """Add one or more owners to an Enterprise Application.

    Each owner can be an email address, a display name, or a directory object ID. An
    address is matched against a user's userPrincipalName and mail, since those routinely
    differ. A GUID is used as-is. A display name is resolved against users and then
    service principals, the only object types that can own a service principal.

    Idempotent by design: the current owners are read once, and an owner that is already
    there is reported as information rather than an error, so this is safe to re-run from
    a pipeline. Owners are resolved and added concurrently.

    Requires Application.ReadWrite.All or Directory.ReadWrite.All. Resolution is exact by
    default, because a prefix match on a write could name the wrong person.

    \b
      pctl azure sp add-owner "Company Incident.io SCIM" ann@company.com
      pctl azure sp add-owner SCIM ann@company.com bob@company.com
      pctl azure sp add-owner SCIM --emails ann@company.com,bob@company.com
      pctl azure sp add-owner SCIM "Ann Example" e6901838-637f-4bc7-b843-a8a7725a4872
      pctl azure sp add-owner SCIM platform-automation --owner-type sp
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    wanted = collect_owners(owners, emails)
    if not wanted:
        raise click.UsageError("Provide at least one owner, positionally or with --emails.")

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        async with graph_client(app) as client:
            target = await resolve_one(client, name, mode=match_mode)
            sp_id = target["id"]
            label = target.get("displayName") or sp_id
            app.log(f"adding {len(wanted)} owner(s) to {label} ({sp_id})")

            resolved, failed = await resolve_owners(
                client, wanted, mode=owner_match, owner_type=owner_type
            )
            existing = {item["id"] async for item in client.owners(sp_id)}

            to_add = [owner for owner in resolved if owner["id"] not in existing]
            if to_add:
                await asyncio.gather(*[client.add_owner(sp_id, owner["id"]) for owner in to_add])

            added = {owner["id"] for owner in to_add}
            records = [
                {
                    "servicePrincipal": label,
                    "owner": owner.get("displayName") or owner["id"],
                    "ownerId": owner["id"],
                    "status": "added" if owner["id"] in added else "already-owner",
                }
                for owner in resolved
            ]
            return records, failed

    records, failed = run(_run())

    with Renderer(app.output, columns=["servicePrincipal", "owner", "ownerId", "status"]) as out:
        out.write_all(records)

    added = [record for record in records if record["status"] == "added"]
    for record in records:
        if record["status"] == "already-owner":
            click.secho(
                f"{record['owner']} is already an owner of {record['servicePrincipal']}.",
                err=True,
                fg="cyan",
            )
    for candidate, reason in failed:
        click.secho(f"Could not resolve '{candidate}': {reason}", err=True, fg="yellow")

    summarise(len(added), "owner added", quiet=app.quiet)
    if failed and not ignore_missing:
        raise NotFoundError(
            f"{len(failed)} of {len(wanted)} owner(s) could not be resolved. "
            "Pass an object ID, or use --ignore-missing to tolerate it."
        )
