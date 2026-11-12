"""Action: `pctl azure apps remove-client-secret`. Removes one client secret from an app.

Removing a secret is immediate and cannot be undone, and whatever still authenticates with
it stops working at once. So the guard here is about time: a secret that has lapsed or is
about to is the ordinary thing to clean up and goes without ceremony, while one with a long
time left may well be in use and is removed only when `--force` says so.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import click

from ...config import AppContext
from ...errors import ConfigError
from ...options import azure_options, output_options
from ...output import Renderer
from .. import graph_client
from .common import (
    CREDENTIAL_SELECT,
    DEFAULT_EXPIRY_WINDOW_DAYS,
    app_options,
    days_remaining,
    find_secret,
    match_option,
    parse_graph_time,
    require_one_app,
    requires_force,
    resolve_app,
)
from .get_client_secrets import utcnow


@click.command(name="remove-client-secret")
@app_options
@click.option(
    "--key-id",
    required=True,
    metavar="KEYID",
    help="Key ID of the client secret to remove, as `get-client-secrets` shows it.",
)
@click.option(
    "--force",
    is_flag=True,
    help=f"Remove a secret that still has more than {DEFAULT_EXPIRY_WINDOW_DAYS} days left.",
)
@azure_options
@match_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    app_name: str | None,
    app_id: str | None,
    key_id: str,
    force: bool,
    match_mode: str,
) -> None:
    """Remove a client secret from an app registration.

    The secret is named by --key-id only, never by name, because names are not unique and
    removal cannot be undone. `get-client-secrets` shows each key ID. Only client secrets can
    be removed. A certificate cannot, because Graph asks for proof of possession of an
    existing certificate to remove one.

    Removal is immediate and permanent, and anything still using the secret stops working.
    A secret that has expired, or has 30 days or fewer left, is removed as asked. One with
    more than 30 days left, or with no end date, is refused unless --force is given.

    This removes the secret from the app registration only. A copy kept in Secrets Manager
    is not touched.

    \b
      pctl azure apps remove-client-secret --app-name "Company Incident.io SCIM" \\
          --key-id 3f1a9c52-0b7d-4e0e-9a54-1c2d3e4f5a6b
      pctl azure apps remove-client-secret --app-id 8f468c48-e9ac-4dd7-973d-9704b9cdd56d \\
          --key-id 3f1a9c52-0b7d-4e0e-9a54-1c2d3e4f5a6b --force
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    require_one_app(app_name, app_id)

    async def _run() -> dict[str, Any]:
        async with graph_client(app) as client:
            registration = await resolve_app(
                client, app_name, app_id, mode=match_mode, select=CREDENTIAL_SELECT
            )
            secret = find_secret(registration, key_id)
            _require_force(secret, force)
            await client.remove_application_password(registration["id"], secret["keyId"])
            return _record(registration, secret)

    record = run(_run())
    with Renderer(app.output, single=True) as renderer:
        renderer.write(record)
    if not app.quiet:
        message = f"Removed client secret '{record['name']}' from {record['app']}."
        click.secho(message, err=True, fg="green")


def _require_force(secret: dict[str, Any], force: bool) -> None:
    """Refuse a secret that is not close to its end, unless `--force` was given."""
    now = utcnow()
    if force or not requires_force(secret, now, timedelta(days=DEFAULT_EXPIRY_WINDOW_DAYS)):
        return
    left = days_remaining(parse_graph_time(secret.get("endDateTime")), now)
    when = "has no end date" if left is None else f"still has {left} days left"
    raise ConfigError(
        f"Client secret '{secret.get('displayName')}' {when}, so it may still be in use. "
        "Removing it cannot be undone. Pass --force to remove it anyway."
    )


def _record(registration: dict[str, Any], secret: dict[str, Any]) -> dict[str, Any]:
    return {
        "app": registration.get("displayName"),
        "appId": registration.get("appId"),
        "name": secret.get("displayName"),
        "keyId": secret.get("keyId"),
        "endDateTime": secret.get("endDateTime"),
        "removed": True,
    }
