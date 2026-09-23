"""The `azure` case: everything that talks to Microsoft Graph.

Layout: this package holds the case-level group plus code shared by all of its
services and actions. Services live in subpackages (`groups`), and case-level
actions that have no service live in their own modules (`token`, `raw`).

Subcommands are declared as import strings so that `pctl azure --help` does not
import httpx or any action module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from ..config import AppContext
from ..lazy import PctlGroup

if TYPE_CHECKING:
    from .graph import GraphClient

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "groups": ("pctl.azure.groups:groups", "List and inspect Entra ID groups."),
    "users": ("pctl.azure.users:users", "Look up Entra ID users."),
    "apps": (
        "pctl.azure.applications:applications",
        "Application registrations, the app objects behind service principals.",
    ),
    "sp": (
        "pctl.azure.service_principals:service_principals",
        "Service principals, known in the portal as Enterprise Applications.",
    ),
    "token": ("pctl.azure.token:command", "Acquire an access token for Microsoft Graph."),
    "raw": ("pctl.azure.raw:command", "Call any Graph path, with auth and pagination handled."),
}

# The portal and Graph disagree on every one of these names, so accept both spellings.
# `apps` and `sp` are the pair most easily confused: an app registration is the
# definition, a service principal is its instance in this tenant.
ALIASES = {
    "enterprise-apps": "sp",
    "service-principals": "sp",
    "app-registrations": "apps",
    "applications": "apps",
}


@click.group(
    name="azure",
    cls=PctlGroup,
    lazy_subcommands=LAZY_SUBCOMMANDS,
    aliases=ALIASES,
    context_settings=CONTEXT_SETTINGS,
)
@click.pass_context
def azure(ctx: click.Context) -> None:
    """Microsoft Graph: tokens, groups, users and service principals.

    \b
    Credentials resolve in this order:
      1. --tenant-id / --client-id flags
      2. AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
      3. --secret-id, reading a JSON secret from AWS Secrets Manager
      4. azure-identity's DefaultAzureCredential, if installed
         (az login, managed identity, workload identity)
    """
    ctx.ensure_object(AppContext)


def graph_client(app: AppContext) -> GraphClient:
    """Build a `GraphClient` from the shared context.

    Every azure action needs the same wiring, so it lives here. The import is
    local to keep httpx out of `--help`.
    """
    from .graph import GraphClient

    return GraphClient(
        app.azure(),
        timeout=app.timeout,
        concurrency=app.concurrency,
        log=app.log,
    )


__all__ = ["ALIASES", "CONTEXT_SETTINGS", "azure", "graph_client"]
