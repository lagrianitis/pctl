"""Action: `pctl azure sp remove-owner`."""

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

# Microsoft's guidance is that a service principal should keep at least two owners, so
# that losing one person does not orphan the application.
RECOMMENDED_MINIMUM_OWNERS = 2


@click.command(name="remove-owner")
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
    """Remove one or more owners from an Enterprise Application.

    Each owner can be an email address, a display name, or a directory object ID, resolved
    the same way as `add-owner`.

    Idempotent by design: the current owners are read once, and an owner that is not there
    is reported as information rather than an error. Owners are resolved and removed
    concurrently.

    Requires Application.ReadWrite.All or Directory.ReadWrite.All. Warns when the removals
    would leave fewer than two owners, which is Microsoft's recommended minimum, but does
    not refuse.

    \b
      pctl azure sp remove-owner "Company Incident.io SCIM" ann@company.com
      pctl azure sp remove-owner SCIM ann@company.com bob@company.com
      pctl azure sp remove-owner SCIM --emails ann@company.com,bob@company.com
      pctl azure sp remove-owner SCIM e6901838-637f-4bc7-b843-a8a7725a4872
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    wanted = collect_owners(owners, emails)
    if not wanted:
        raise click.UsageError("Provide at least one owner, positionally or with --emails.")

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]], int]:
        async with graph_client(app) as client:
            target = await resolve_one(client, name, mode=match_mode)
            sp_id = target["id"]
            label = target.get("displayName") or sp_id
            app.log(f"removing {len(wanted)} owner(s) from {label} ({sp_id})")

            resolved, failed = await resolve_owners(
                client, wanted, mode=owner_match, owner_type=owner_type
            )
            existing = {item["id"] async for item in client.owners(sp_id)}

            to_remove = [owner for owner in resolved if owner["id"] in existing]
            if to_remove:
                await asyncio.gather(
                    *[client.remove_owner(sp_id, owner["id"]) for owner in to_remove]
                )

            removed = {owner["id"] for owner in to_remove}
            records = [
                {
                    "servicePrincipal": label,
                    "owner": owner.get("displayName") or owner["id"],
                    "ownerId": owner["id"],
                    "status": "removed" if owner["id"] in removed else "not-an-owner",
                }
                for owner in resolved
            ]
            return records, failed, len(existing) - len(removed)

    records, failed, remaining = run(_run())

    with Renderer(app.output, columns=["servicePrincipal", "owner", "ownerId", "status"]) as out:
        out.write_all(records)

    removed = [record for record in records if record["status"] == "removed"]
    for record in records:
        if record["status"] == "not-an-owner":
            click.secho(
                f"{record['owner']} is not an owner of {record['servicePrincipal']}.",
                err=True,
                fg="cyan",
            )
    for candidate, reason in failed:
        click.secho(f"Could not resolve '{candidate}': {reason}", err=True, fg="yellow")

    summarise(len(removed), "owner removed", quiet=app.quiet)
    if removed and remaining < RECOMMENDED_MINIMUM_OWNERS:
        click.secho(
            f"{records[0]['servicePrincipal']} now has {remaining} owner(s). "
            f"Microsoft recommends at least {RECOMMENDED_MINIMUM_OWNERS}.",
            err=True,
            fg="yellow",
        )
    if failed and not ignore_missing:
        raise NotFoundError(
            f"{len(failed)} of {len(wanted)} owner(s) could not be resolved. "
            "Pass an object ID, or use --ignore-missing to tolerate it."
        )
