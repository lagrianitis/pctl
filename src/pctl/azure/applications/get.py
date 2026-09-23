"""Action: `pctl azure apps get`."""

from __future__ import annotations

import asyncio
from typing import Any

import click

from ...config import AppContext
from ...errors import ConfigError, NotFoundError
from ...options import (
    azure_options,
    columns_option,
    output_options,
    read_names,
    split_columns,
)
from ...output import Renderer, summarise
from .. import graph_client
from .common import DEFAULT_LIST_COLUMNS, match_option, resolve_application


@click.command(name="get")
@click.option(
    "--app",
    "identifiers",
    multiple=True,
    metavar="NAME|APPID|ID",
    help="Display name, appId or object ID. Repeat for several.",
)
@azure_options
@click.option(
    "-f",
    "--from-file",
    metavar="PATH",
    help="Read identifiers from a file, one per line ('-' for stdin).",
)
@match_option
@click.option(
    "--with-sp",
    is_flag=True,
    help="Also fetch the service principal that instantiates the app in this tenant.",
)
@click.option(
    "--select", metavar="FIELDS", help="Comma-separated Graph fields to request."
)
@click.option(
    "--ignore-missing",
    is_flag=True,
    help="Exit 0 even when an identifier matches nothing.",
)
@columns_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    identifiers: tuple[str, ...],
    from_file: str | None,
    match_mode: str,
    with_sp: bool,
    select: str | None,
    ignore_missing: bool,
) -> None:
    """Show an application registration, by display name, appId or object ID.

    An application has two GUIDs and they are not interchangeable. `appId` is the
    Application (client) ID, shared with its service principal. `id` is its own directory
    object. A bare GUID is tried as an appId first, because that is the one the portal
    shows prominently, then as an object ID.

    --with-sp adds the service principal for the same appId under `servicePrincipal`,
    which is how to get from a registration to the Enterprise Application it appears as.
    Its `id` differs from the application's, and that difference is the usual source of
    "no such object" errors.

    \b
      pctl azure apps get --app "Company Incident.io SCIM"
      pctl azure apps get --app 8f468c48-e9ac-4dd7-973d-9704b9cdd56d
      pctl azure apps get --app "Company Incident.io SCIM" --with-sp -o json
      pctl azure apps get --app "incident" --match search
      pctl azure apps get -f apps.txt --ignore-missing
    """
    from ..graph import DEFAULT_APPLICATION_SELECT, run

    app = ctx.ensure_object(AppContext)
    wanted = read_names(identifiers, from_file)
    if not wanted:
        raise click.UsageError(
            "Provide at least one display name, appId or object ID with --app, or use --from-file."
        )

    fields = tuple(split_columns(select) or DEFAULT_APPLICATION_SELECT)
    table_columns = app.columns or _columns(with_sp, list(fields) if select else None)

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        async with graph_client(app) as client:
            app.log(f"resolving {len(wanted)} identifier(s)")

            async def one(identifier: str) -> dict[str, Any] | tuple[str, str]:
                try:
                    found = await resolve_application(
                        client, identifier, mode=match_mode, select=fields
                    )
                except (NotFoundError, ConfigError) as exc:
                    return identifier, str(exc)
                found["_query"] = identifier
                return found

            results = await asyncio.gather(*[one(item) for item in wanted])
            found = [item for item in results if isinstance(item, dict)]
            failed = [item for item in results if isinstance(item, tuple)]

            if found and with_sp:
                app.log(f"fetching service principals for {len(found)} app(s)")
                principals = await asyncio.gather(
                    *[
                        client.find_service_principal_by_app_id(item["appId"])
                        for item in found
                    ]
                )
                for item, principal in zip(found, principals, strict=True):
                    item["servicePrincipal"] = principal
                    item["servicePrincipalId"] = (principal or {}).get("id")
            return found, failed

    found, failed = run(_run())

    with Renderer(
        app.output, columns=table_columns, single=len(found) == 1
    ) as renderer:
        renderer.write_all(found)

    for _identifier, reason in failed:
        click.secho(reason, err=True, fg="yellow")
    for item in found:
        if with_sp and item.get("servicePrincipalId") is None:
            click.secho(
                f"{item.get('displayName')} has no service principal in this tenant, "
                "so it is registered but not instantiated here.",
                err=True,
                fg="cyan",
            )

    summarise(len(found), "app registration", quiet=app.quiet)
    if failed and not ignore_missing:
        raise NotFoundError(
            f"{len(failed)} of {len(wanted)} identifier(s) matched nothing."
        )


def _columns(with_sp: bool, selected: list[str] | None) -> list[str]:
    columns = selected or list(DEFAULT_LIST_COLUMNS)
    if with_sp:
        columns = [*columns, "servicePrincipalId"]
    return columns
