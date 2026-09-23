"""Action: `pctl azure eam remove-assignment`."""

from __future__ import annotations

import asyncio
from typing import Any

import click

from ...config import AppContext
from ...errors import ConfigError, NotFoundError
from ...options import azure_options, output_options
from ...output import Renderer, summarise
from .. import graph_client
from ..common import find_user
from .common import (
    ACTIVE_ASSIGNMENT_STATES,
    assignment_request,
    collect_targets,
    report_outcomes,
    resolve_package_id,
    settle_requests,
    target_options,
)

RESULT_COLUMNS = [
    "accessPackage",
    "target",
    "targetId",
    "status",
    "requestId",
    "requestState",
]
USER_FIELDS = ("id", "displayName", "userPrincipalName", "mail")


@click.command(name="remove-assignment")
@click.option(
    "--access-package",
    "package",
    required=True,
    metavar="NAME|ID",
    help="The access package to revoke. Display name or object ID.",
)
@click.option(
    "--target",
    "targets",
    multiple=True,
    metavar="EMAIL|NAME|ID",
    help="Person whose assignment to remove. Repeat for several.",
)
@azure_options
@target_options
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    package: str,
    targets: tuple[str, ...],
    emails: str | None,
    ignore_missing: bool,
    wait: bool,
    wait_timeout: float,
) -> None:
    """Remove one or more people's assignment to an access package.

    --access-package is a display name or ID. Each --target is an email address, a display
    name or a user object ID.

    Idempotent: current assignments are read first, and someone who has none is reported
    rather than sent as a request. No policy is needed, unlike add-assignment: an
    adminRemove names the existing assignment rather than the rules that created it.

    This creates an adminRemove request, which Graph applies afterwards, so without --wait
    access may still be live when the command returns. That matters more here than for
    add: if you are revoking access in response to an incident, exit 0 without --wait does
    not mean the access is gone.

    --wait polls each request until it is delivered and exits 5 if any is not, bounded by
    --wait-timeout.

    Requires EntitlementManagement.ReadWrite.All.

    \b
      pctl azure eam remove-assignment --access-package "$PKG" --target ann@company.com --wait
      pctl azure eam remove-assignment --access-package "$PKG" --emails a@b.com,c@d.com --wait
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    wanted = collect_targets(targets, emails)
    if not wanted:
        raise click.UsageError("Provide at least one person with --target or --emails.")

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        async with graph_client(app) as client:
            package_id = await resolve_package_id(client, package)
            app.log(f"package={package_id} targets={len(wanted)}")

            async def one(identifier: str) -> dict[str, Any] | tuple[str, str]:
                try:
                    user = await find_user(client, identifier, select=USER_FIELDS)
                except (NotFoundError, ConfigError) as exc:
                    return identifier, str(exc)
                record: dict[str, Any] = {
                    "accessPackage": package,
                    "target": user.get("displayName") or identifier,
                    "targetId": user["id"],
                }
                existing = await client.find_assignment(
                    package_id, user["id"], states=ACTIVE_ASSIGNMENT_STATES
                )
                if existing is None:
                    return {
                        **record,
                        "status": "not-assigned",
                        "requestId": None,
                        "requestState": None,
                    }
                created = await client.create_assignment_request(
                    assignment_request(request_type="adminRemove", id=str(existing["id"]))
                )
                return {
                    **record,
                    "status": "removal-requested",
                    "requestId": created.get("id"),
                    "requestState": created.get("state"),
                }

            results = await asyncio.gather(*[one(item) for item in wanted])
            records = [item for item in results if isinstance(item, dict)]
            if wait:
                await settle_requests(client, records, timeout=wait_timeout, log=app.log)
            return (
                records,
                [item for item in results if isinstance(item, tuple)],
            )

    records, failed = run(_run())

    columns = RESULT_COLUMNS if not wait else [*RESULT_COLUMNS, "outcome"]
    with Renderer(app.output, columns=columns) as renderer:
        renderer.write_all(records)

    for record in records:
        if record["status"] == "not-assigned":
            click.secho(
                f"{record['target']} has no live assignment to {record['accessPackage']}; "
                "nothing to do.",
                err=True,
                fg="cyan",
            )
    for identifier, reason in failed:
        click.secho(f"Could not resolve '{identifier}': {reason}", err=True, fg="yellow")

    removed = [record for record in records if record["status"] == "removal-requested"]
    summarise(len(removed), "removal requested", quiet=app.quiet)

    if failed and not ignore_missing:
        raise NotFoundError(
            f"{len(failed)} of {len(wanted)} target(s) could not be resolved. "
            "Pass a user object ID, or use --ignore-missing."
        )
    if wait:
        report_outcomes(removed, noun="removal", quiet=app.quiet)
    elif removed and not app.quiet:
        click.secho(
            "Requests are processed asynchronously; the access is not gone yet. Confirm "
            "with --wait, or `eam get-request <id>`.",
            err=True,
            fg="yellow",
        )
