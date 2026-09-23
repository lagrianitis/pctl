"""Action: `pctl azure eam get-request`."""

from __future__ import annotations

from typing import Any

import click

from ...config import AppContext
from ...errors import UpstreamError
from ...options import azure_options, columns_option, output_options
from ...output import Renderer
from .. import graph_client
from .common import request_outcome, wait_for_request

COLUMNS = ["id", "requestType", "state", "outcome", "targetDisplayName", "accessPackageName"]


@click.command(name="get-request")
@click.option(
    "--request-id",
    "request_id",
    required=True,
    metavar="ID",
    help="The requestId returned by add-assignment or remove-assignment.",
)
@azure_options
@click.option(
    "--wait",
    is_flag=True,
    help="Poll until the request settles rather than reporting its current state.",
)
@click.option(
    "--wait-timeout",
    type=click.FloatRange(min=1),
    default=120.0,
    show_default=True,
    metavar="SECONDS",
    help="Give up waiting after this long. Still-pending is reported, not an error.",
)
@click.option(
    "--fail-on-pending",
    is_flag=True,
    help="Exit 5 when the request has not settled, instead of exiting 0.",
)
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    request_id: str,
    wait: bool,
    wait_timeout: float,
    fail_on_pending: bool,
) -> None:
    """Show an assignment request, to find out whether a write actually landed.

    add-assignment and remove-assignment are asynchronous: they return a requestId and
    Graph applies the change afterwards. This reports where that request got to.

    The outcome column classifies the raw state: done only for `delivered`, failed for
    `denied`, `canceled` or `deliveryFailed`, partial for `partiallyDelivered`, and
    pending for everything else including unrecognised states. A request can sit in
    `delivering` indefinitely when provisioning is stuck, so an unknown state is treated
    as pending rather than assumed finished.

    Exits 5 for a failed or partial request, so a pipeline can branch on it. A pending
    request exits 0 unless --fail-on-pending.

    \b
      pctl azure eam get-request --request-id 4c2a1f7e-...
      pctl azure eam get-request --request-id 4c2a1f7e-... --wait
      pctl azure eam get-request --request-id 4c2a1f7e-... --wait --fail-on-pending
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)

    async def _run() -> dict[str, Any]:
        async with graph_client(app) as client:
            if wait:
                return await wait_for_request(client, request_id, timeout=wait_timeout, log=app.log)
            return await client.get_assignment_request(request_id)

    found = run(_run())
    record = _shape(found)

    with Renderer(app.output, columns=app.columns or COLUMNS, single=True) as renderer:
        renderer.write(record)

    _report(record, fail_on_pending=fail_on_pending, quiet=app.quiet)


def _shape(request: dict[str, Any]) -> dict[str, Any]:
    """Lift the expanded names up and add the outcome classification."""
    target = request.get("target") or {}
    package = request.get("accessPackage") or {}
    state = request.get("state") or request.get("requestState")
    request["outcome"] = request_outcome(state)
    request["state"] = state
    request["targetDisplayName"] = target.get("displayName") or target.get("email")
    request["accessPackageName"] = package.get("displayName")
    return request


def _report(record: dict[str, Any], *, fail_on_pending: bool, quiet: bool) -> None:
    """Turn the outcome into a message and, where it matters, a non-zero exit."""
    outcome = record["outcome"]
    state = record.get("state")
    if outcome == "done":
        if not quiet:
            click.secho(f"Request {record.get('id')} is delivered.", err=True, fg="green")
        return
    if outcome == "failed":
        raise UpstreamError(f"Request {record.get('id')} did not apply: state {state}.")
    if outcome == "partial":
        raise UpstreamError(
            f"Request {record.get('id')} only partly applied: state {state}. "
            "Microsoft's guidance is to reprocess rather than resubmit it."
        )
    message = f"Request {record.get('id')} has not settled: state {state}."
    if fail_on_pending:
        raise UpstreamError(message)
    click.secho(message, err=True, fg="yellow")
