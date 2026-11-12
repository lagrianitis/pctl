"""Action: `pctl azure apps credentials`."""

from __future__ import annotations

import click

from ...config import AppContext
from ...options import azure_options, columns_option, output_options
from ...output import Renderer, summarise
from .. import graph_client
from .common import (
    CREDENTIAL_SELECT,
    DEFAULT_CREDENTIAL_COLUMNS,
    credential_rows,
    match_option,
    resolve_application,
)


@click.command(name="credentials")
@click.option(
    "--app",
    "identifier",
    required=True,
    metavar="NAME|APPID|ID",
    help="Display name, appId or object ID of the app registration.",
)
@azure_options
@match_option
@columns_option
@output_options
@click.pass_context
def command(ctx: click.Context, identifier: str, match_mode: str) -> None:
    """List the client secrets and certificates of an app registration.

    The app is found the way `apps get` finds it: a bare GUID is tried as an appId first
    and then as an object ID, and a display name is matched with --match. An ambiguous name
    is refused rather than guessed.

    Graph never returns the value of an existing secret. What it returns, and what is shown
    here, is the name, the key ID, the start and end dates and a short hint. A secret's
    value is shown once, when it is created, and this command does not create one.

    Federated credentials are a separate resource and are not listed.

    \b
      pctl azure apps credentials --app "Company Incident.io SCIM"
      pctl azure apps credentials --app 8f468c48-e9ac-4dd7-973d-9704b9cdd56d -o json
      pctl azure apps credentials --app "incident" --match search
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)

    async def _run() -> dict[str, object]:
        async with graph_client(app) as client:
            return await resolve_application(
                client, identifier, mode=match_mode, select=CREDENTIAL_SELECT
            )

    registration = run(_run())
    rows = credential_rows(registration)

    with Renderer(app.output, columns=app.columns or DEFAULT_CREDENTIAL_COLUMNS) as renderer:
        renderer.write_all(rows)
    if not rows:
        click.secho(
            f"{registration.get('displayName')} has no client secrets or certificates.",
            err=True,
            fg="cyan",
        )
    summarise(len(rows), "credential", quiet=app.quiet)
