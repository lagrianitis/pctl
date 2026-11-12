"""Action: `pctl azure apps credentials`."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import click

from ...config import AppContext
from ...errors import CheckFailedError
from ...options import azure_options, columns_option, output_options
from ...output import Renderer, summarise
from .. import graph_client
from .common import (
    ATTENTION_STATUSES,
    CREDENTIAL_SELECT,
    DEFAULT_CREDENTIAL_COLUMNS,
    DEFAULT_EXPIRY_WINDOW_DAYS,
    STATUS_EXPIRED,
    STATUS_EXPIRING,
    credential_rows,
    match_option,
    resolve_application,
    with_expiry,
)


def utcnow() -> datetime:
    """The current time, in a function of its own so a test can fix it."""
    return datetime.now(UTC)


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
@click.option(
    "--expiring-within",
    "window_days",
    type=click.IntRange(min=1),
    default=DEFAULT_EXPIRY_WINDOW_DAYS,
    show_default=True,
    metavar="DAYS",
    help="A credential ending within this many days is reported as expiring.",
)
@click.option(
    "--fail-on-expiry",
    is_flag=True,
    help="Exit 6 when any credential has expired or is expiring, after listing them.",
)
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    identifier: str,
    match_mode: str,
    window_days: int,
    fail_on_expiry: bool,
) -> None:
    """List the client secrets and certificates of an app registration, and when they end.

    The app is found the way `apps get` finds it: a bare GUID is tried as an appId first
    and then as an object ID, and a display name is matched with --match. An ambiguous name
    is refused rather than guessed.

    Each credential shows the days it has left, rounded down and negative once it has
    lapsed, and a status: expired, expiring (ending within --expiring-within days) or
    valid. Dates are UTC, as Graph reports them. Listed soonest to end first.

    --fail-on-expiry makes the command usable as a check: it still lists everything, then
    exits 6 if any credential has expired or is expiring. An app with no credentials
    passes.

    Graph never returns the value of an existing secret. What it returns, and what is shown
    here, is the name, the key ID, the dates and a short hint. A secret's value is shown
    once, when it is created, and this command does not create one.

    Federated credentials are a separate resource and are not listed.

    \b
      pctl azure apps credentials --app "Company Incident.io SCIM"
      pctl azure apps credentials --app 8f468c48-e9ac-4dd7-973d-9704b9cdd56d -o json
      pctl azure apps credentials --app "incident" --match search
      pctl azure apps credentials --app "Company SCIM" --expiring-within 60 --fail-on-expiry
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)

    async def _run() -> dict[str, Any]:
        async with graph_client(app) as client:
            return await resolve_application(
                client, identifier, mode=match_mode, select=CREDENTIAL_SELECT
            )

    registration = run(_run())
    window = timedelta(days=window_days)
    rows = with_expiry(credential_rows(registration), utcnow(), window)

    with Renderer(app.output, columns=app.columns or DEFAULT_CREDENTIAL_COLUMNS) as renderer:
        renderer.write_all(rows)
    if not rows:
        click.secho(
            f"{registration.get('displayName')} has no client secrets or certificates.",
            err=True,
            fg="cyan",
        )
    summarise(len(rows), "credential", quiet=app.quiet)
    _report_expiry(rows, window_days, fail_on_expiry)


def _report_expiry(rows: list[dict[str, Any]], window_days: int, fail: bool) -> None:
    """Say what has lapsed or is about to, and fail if the caller asked for a check."""
    counts = Counter(row["status"] for row in rows)
    if not any(counts[status] for status in ATTENTION_STATUSES):
        return
    message = (
        f"{counts[STATUS_EXPIRED]} expired and {counts[STATUS_EXPIRING]} expiring "
        f"within {window_days} days, of {len(rows)} credential(s)."
    )
    if fail:
        raise CheckFailedError(message)
    click.secho(message, err=True, fg="yellow")
