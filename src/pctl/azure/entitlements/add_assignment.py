"""Action: `pctl azure eam add-assignment`."""

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
    resolve_policy_id,
    settle_requests,
    target_options,
)

RESULT_COLUMNS = ["accessPackage", "target", "targetId", "status", "requestId", "requestState"]
USER_FIELDS = ("id", "displayName", "userPrincipalName", "mail")


@click.command(name="add-assignment")
@click.argument("package")
@click.argument("targets", nargs=-1)
@azure_options
@target_options
@click.option(
    "--policy",
    metavar="NAME|ID",
    help="Assignment policy to use. Needed only when the package has more than one.",
)
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
    policy: str | None,
) -> None:
    """Assign one or more people to an access package.

    PACKAGE is a display name or ID. Each target is an email address, a display name or a
    user object ID; an address is matched against userPrincipalName and mail, since those
    routinely differ.

    Idempotent: existing assignments are read first, and someone who already has live
    access is reported rather than re-requested. Expired assignments do not block a fresh
    add, because an expired assignment is not access.

    This creates an adminAdd request rather than writing an assignment directly, so Graph
    applies it afterwards. Without --wait the command reports the state at submission,
    which is not yet access.

    --wait polls each request until it is delivered and exits 5 if any is not, so a
    pipeline can depend on the access actually existing. A request can stall in
    `delivering` indefinitely, so waiting is bounded by --wait-timeout and a request still
    pending at that point is reported as such rather than assumed good.

    Requires EntitlementManagement.ReadWrite.All.

    \b
      pctl azure eam add-assignment "AWS Platform Access" ann@company.com
      pctl azure eam add-assignment PKG ann@company.com --wait
      pctl azure eam add-assignment PKG --emails ann@company.com,bob@company.com --wait
      pctl azure eam add-assignment PKG ann@company.com --policy "Direct assignment"
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    wanted = collect_targets(targets, emails)
    if not wanted:
        raise click.UsageError("Provide at least one person, positionally or with --emails.")

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        async with graph_client(app) as client:
            package_id = await resolve_package_id(client, package)
            policy_id = await resolve_policy_id(client, package_id, policy)
            app.log(f"package={package_id} policy={policy_id} targets={len(wanted)}")

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
                if existing is not None:
                    return {
                        **record,
                        "status": "already-assigned",
                        "requestId": None,
                        "requestState": existing.get("state"),
                    }
                created = await client.create_assignment_request(
                    assignment_request(
                        request_type="adminAdd",
                        targetId=user["id"],
                        assignmentPolicyId=policy_id,
                        accessPackageId=package_id,
                    )
                )
                return {
                    **record,
                    "status": "requested",
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
        if record["status"] == "already-assigned":
            click.secho(
                f"{record['target']} already has {record['accessPackage']} "
                f"({record['requestState']}); nothing to do.",
                err=True,
                fg="cyan",
            )
    for identifier, reason in failed:
        click.secho(f"Could not resolve '{identifier}': {reason}", err=True, fg="yellow")

    requested = [record for record in records if record["status"] == "requested"]
    summarise(len(requested), "assignment requested", quiet=app.quiet)

    if failed and not ignore_missing:
        raise NotFoundError(
            f"{len(failed)} of {len(wanted)} target(s) could not be resolved. "
            "Pass a user object ID, or use --ignore-missing."
        )
    if wait:
        report_outcomes(requested, noun="assignment", quiet=app.quiet)
    elif requested and not app.quiet:
        click.secho(
            "Requests are processed asynchronously and are not applied yet. Confirm with "
            "--wait, or `eam get-request <id>`.",
            err=True,
            fg="yellow",
        )
