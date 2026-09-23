"""The list and get bodies, shared by both entitlement management collections.

Access packages and catalogs differ only in path, default fields and the noun used in
messages. Writing the flow twice would mean two places to fix when the OData surface of
these collections changes, which it already has once between beta and v1.0.
"""

from __future__ import annotations

from typing import Any

import click

from ...config import AppContext
from ...options import split_columns
from ...output import Renderer, summarise
from .. import graph_client
from .common import build_filter, contains_filter, resolve_catalog_id, resolve_one


def run_list(
    ctx: click.Context,
    *,
    collection: str,
    noun: str,
    default_select: tuple[str, ...],
    default_columns: list[str],
    select: str | None,
    filter_expr: str | None,
    name: str | None,
    starts_with: str | None,
    contains: str | None,
    limit: int | None,
    page_size: int,
    catalog: str | None = None,
) -> None:
    """List one entitlement management collection."""
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    fields = split_columns(select) or list(default_select)
    columns = app.columns or (fields if select else default_columns)

    async def _run() -> int:
        async with graph_client(app) as client:
            server_filter = build_filter(filter_expr, name, starts_with)
            if catalog and not filter_expr:
                # Resolve the catalog first so the scope can be expressed as a name. The
                # filter needs its id, and asking people to look that up themselves is
                # the friction this whole service exists to remove.
                resolved = await resolve_catalog_id(client, catalog)
                scope = f"catalog/id eq '{resolved}'"
                server_filter = f"{server_filter} and {scope}" if server_filter else scope
            app.log(f"listing {collection} filter={server_filter or 'none'}")
            # `--contains` cannot be pushed to Graph, so the limit has to be applied
            # after filtering or it would cap the wrong set.
            stream = client.list_governance(
                collection,
                select=fields,
                filter_expr=server_filter,
                limit=None if contains else limit,
                page_size=page_size,
            )
            if contains:
                matched = contains_filter([item async for item in stream], contains)
                if limit is not None:
                    matched = matched[:limit]
                with Renderer(app.output, columns=columns) as renderer:
                    renderer.write_all(matched)
                return len(matched)
            renderer = Renderer(app.output, columns=columns)
            async for item in stream:
                renderer.write(item)
            return renderer.close()

    summarise(run(_run()), noun, quiet=app.quiet)


def run_get(
    ctx: click.Context,
    *,
    collection: str,
    noun: str,
    identifier: str,
    match_mode: str,
    default_select: tuple[str, ...],
    select: str | None,
    expand: tuple[str, ...] | None = None,
) -> None:
    """Show one object from an entitlement management collection."""
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    fields = tuple(split_columns(select) or default_select)

    async def _run() -> dict[str, Any]:
        async with graph_client(app) as client:
            found = await resolve_one(
                client,
                collection,
                identifier,
                noun=noun,
                mode=match_mode,
                select=fields,
                expand=expand,
            )
            app.log(f"resolved '{identifier}' to {found.get('displayName')} ({found.get('id')})")
            return found

    found = run(_run())
    with Renderer(app.output, columns=app.columns, single=True) as renderer:
        renderer.write(found)
