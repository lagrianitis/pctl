"""Action: `pctl azure eam delete-package`.

The only destructive command in the CLI, so it is the only one that asks before acting and
the only one that looks at the state of a thing before removing it. Both guards exist
because a deleted access package cannot be restored: its policies, resource roles and
request history go with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ...config import AppContext
from ...errors import ConfigError, NotFoundError
from ...options import azure_options, output_options
from ...output import Renderer, summarise
from .. import graph_client
from ..common import looks_like_object_id

if TYPE_CHECKING:
    from ..graph import GraphClient

RESULT_COLUMNS = ["accessPackage", "accessPackageId", "status"]

# Graph refuses the delete while any accessPackageAssignment exists, whatever its state,
# so the pre-check counts them all rather than only the live ones. Fetching the state as
# well costs nothing and lets the refusal say what is in the way.
ASSIGNMENT_FIELDS = ("id", "state")


@click.command(name="delete-package")
@click.option(
    "--access-package",
    "identifier",
    required=True,
    metavar="NAME|ID",
    help="The access package to delete. Exact display name or object ID.",
)
@azure_options
@click.option(
    "--yes",
    is_flag=True,
    help="Skip the confirmation prompt. Required when stdin is not a terminal.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip the assignment pre-check and let Graph accept or refuse the delete.",
)
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    identifier: str,
    yes: bool,
    force: bool,
) -> None:
    """Delete an access package. This cannot be undone.

    Takes one package, by exact display name or object ID. Unlike every other eam command
    there is no --match and no substring fallback: a pattern can match more than one
    package, and `Retired` resolving to `Retired Access` is not a mistake worth risking
    here. An ambiguous name is refused with the candidate IDs listed.

    Graph will not delete a package that still has assignments, so this checks first and
    tells you how many are in the way rather than passing back a bare 400. Remove them with
    `eam remove-assignment` first. `--force` skips the check and lets Graph decide, which is
    only useful if you believe the check is being over-cautious.

    Asks for confirmation unless --yes is passed, and naming the package in the prompt is
    the point: the confirmation happens after resolution, so you see exactly what is about
    to go. In a pipeline stdin is not a terminal and --yes is required.

    Deleting takes the package's policies, resource role assignments and request history
    with it. Consider hiding the package instead if you only want it out of the catalog.

    Requires EntitlementManagement.ReadWrite.All.

    \b
      pctl azure eam delete-package --access-package "Retired Access"
      pctl azure eam delete-package --access-package a914b616-e04e-476b-aa37-91038f0b165b
      pctl azure eam delete-package --access-package "Retired Access" --yes
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)

    async def _resolve() -> tuple[str, str, list[dict[str, Any]]]:
        async with graph_client(app) as client:
            package = await resolve_exactly_one(client, identifier)
            package_id = str(package["id"])
            label = str(package.get("displayName") or package_id)
            blockers = [] if force else await assignments_for(client, package_id)
            return package_id, label, blockers

    # Two round trips of client setup rather than one, so that the prompt sits between them
    # instead of blocking on stdin inside the event loop. The cost is one cached-token read;
    # the gain is that nothing is in flight while a human is being asked a question.
    package_id, label, blockers = run(_resolve())
    if blockers:
        raise ConfigError(describe_blockers(label, blockers))

    confirm(label, package_id, assumed=yes)

    async def _delete() -> None:
        async with graph_client(app) as client:
            app.log(f"deleting access package {label} ({package_id})")
            await client.delete_access_package(package_id)

    run(_delete())

    record = {
        "accessPackage": label,
        "accessPackageId": package_id,
        "status": "deleted",
    }
    with Renderer(app.output, columns=RESULT_COLUMNS, single=True) as renderer:
        renderer.write(record)
    summarise(1, "deleted access package", quiet=app.quiet)


async def resolve_exactly_one(client: GraphClient, identifier: str) -> dict[str, Any]:
    """Resolve an object ID or an exact display name to one access package.

    Deliberately not `resolve_package_id`. That one falls back to a substring match when
    the exact name finds nothing, which is a helpful convenience when the answer becomes a
    filter — and an unacceptable one when it becomes a delete. `Retired` quietly resolving
    to `Retired Access` is exactly the accident this command must not have.

    An object ID is fetched rather than trusted, so a typo fails as a lookup before
    anything is deleted.
    """
    if looks_like_object_id(identifier):
        return await client.get_governance(
            "accessPackages", identifier.strip(), select=("id", "displayName")
        )

    matches = await client.find_governance_by_display_name(
        "accessPackages",
        identifier,
        mode="exact",
        select=("id", "displayName"),
        limit=2,
    )
    if not matches:
        raise NotFoundError(
            f"No access package is named exactly '{identifier}'. Deleting needs an exact "
            "name or an object ID; find it with `pctl azure eam get-package "
            f"--access-package {identifier!r} --match contains`."
        )
    if len(matches) > 1:
        ids = ", ".join(str(item.get("id")) for item in matches)
        raise ConfigError(
            f"{len(matches)} access packages are named '{identifier}' ({ids}). "
            "Pass the object ID of the one to delete."
        )
    return matches[0]


async def assignments_for(client: GraphClient, package_id: str) -> list[dict[str, Any]]:
    """Every assignment on a package, whatever its state.

    Fetched in full rather than counted: `$count` is not supported on entitlement
    management collections, and the states are what make the refusal actionable.
    """
    from ..graph import escape_odata

    return [
        item
        async for item in client.list_governance(
            "assignments",
            select=ASSIGNMENT_FIELDS,
            filter_expr=f"accessPackage/id eq '{escape_odata(package_id)}'",
        )
    ]


def describe_blockers(label: str, blockers: list[dict[str, Any]]) -> str:
    """Explain which assignments are preventing the delete, and what to do about them."""
    states: dict[str, int] = {}
    for item in blockers:
        state = str(item.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
    breakdown = ", ".join(f"{count} {state}" for state, count in sorted(states.items()))
    return (
        f"'{label}' still has {len(blockers)} assignment(s) ({breakdown}), and Graph will "
        "not delete a package that has any. Remove them first with "
        "`pctl azure eam remove-assignment`, or pass --force to try the delete anyway."
    )


def confirm(label: str, package_id: str, *, assumed: bool) -> None:
    """Ask before deleting, unless --yes was passed.

    Declining aborts rather than exiting 0, so a wrapper script cannot read a refused
    delete as a successful one.
    """
    if assumed:
        return
    click.confirm(
        f"Delete access package '{label}' ({package_id})? This cannot be undone.",
        abort=True,
        err=True,
    )
