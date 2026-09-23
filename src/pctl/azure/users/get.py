"""Action: `pctl azure users get`."""

from __future__ import annotations

import asyncio
from typing import Any

import click

from ...config import AppContext
from ...errors import NotFoundError
from ...options import (
    azure_options,
    columns_option,
    output_options,
    read_names,
    split_columns,
)
from ...output import Renderer, summarise
from .. import graph_client
from ..common import find_user
from .common import DEFAULT_LIST_COLUMNS, match_option


@click.command(name="get")
@click.option(
    "--user",
    "identifiers",
    multiple=True,
    metavar="EMAIL|NAME|ID",
    help="Email address, display name or object ID. Repeat for several.",
)
@azure_options
@click.option(
    "-f",
    "--from-file",
    metavar="PATH",
    help="Read identifiers from a file, one per line ('-' for stdin).",
)
@match_option
@click.option("--select", metavar="FIELDS", help="Comma-separated Graph fields to request.")
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
    select: str | None,
    ignore_missing: bool,
) -> None:
    """Show a user, found by email address, display name or object ID.

    Which form you passed is inferred, so there is no flag to set. An address is matched
    against both userPrincipalName and mail, since those routinely differ. A display name
    uses --match, and an ambiguous name is refused rather than guessed, because two people
    can share one.

    Repeat --user for several people. They are resolved concurrently, and one that matches
    nothing does not block the others.

    \b
      pctl azure users get --user ann@company.com
      pctl azure users get --user "Ann Example" -o json
      pctl azure users get --user e6901838-637f-4bc7-b843-a8a7725a4872
      pctl azure users get --user ann@company.com --user bob@company.com -o ndjson
      pctl azure users get -f people.txt --ignore-missing
      pctl azure users get --user "Ann" --match prefix
    """
    from ..graph import DEFAULT_USER_SELECT, run

    app = ctx.ensure_object(AppContext)
    wanted = read_names(identifiers, from_file)
    if not wanted:
        raise click.UsageError(
            "Provide at least one email address, display name or object ID with --user, "
            "or use --from-file."
        )

    fields = tuple(split_columns(select) or DEFAULT_USER_SELECT)
    table_columns = app.columns or (list(fields) if select else DEFAULT_LIST_COLUMNS)

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        async with graph_client(app) as client:
            app.log(f"resolving {len(wanted)} identifier(s)")

            async def one(identifier: str) -> dict[str, Any] | tuple[str, str]:
                # Only NotFoundError is collected. A ConfigError here means the identifier
                # was ambiguous, which --ignore-missing must not swallow: skipping a name
                # that matched two people would quietly drop one of them. It propagates as
                # a usage error instead, which is what the message already tells the
                # caller to fix.
                try:
                    found = await find_user(client, identifier, select=fields, mode=match_mode)
                except NotFoundError as exc:
                    return identifier, str(exc)
                found["_query"] = identifier
                return found

            results = await asyncio.gather(*[one(item) for item in wanted])
            return (
                [item for item in results if isinstance(item, dict)],
                [item for item in results if isinstance(item, tuple)],
            )

    found, failed = run(_run())

    with Renderer(app.output, columns=table_columns, single=len(found) == 1) as renderer:
        renderer.write_all(found)

    for _identifier, reason in failed:
        # The reason already names the identifier, so printing it again reads as a stutter.
        click.secho(reason, err=True, fg="yellow")

    summarise(len(found), "user", quiet=app.quiet)
    if failed and not ignore_missing:
        raise NotFoundError(f"{len(failed)} of {len(wanted)} identifier(s) matched nothing.")
