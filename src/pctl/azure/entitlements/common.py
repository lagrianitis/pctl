"""Code shared by the `eam` actions.

Access packages and catalogs are the same query problem twice: a nested collection with a
narrower OData surface than the rest of Graph. The list and resolve bodies are therefore
written once here and parameterised by collection, rather than copied into each action.

What is genuinely specific to entitlement management, and the reason this does not reuse
the directory helpers, is that `$search` and `$count` are not supported. A substring match
has to happen locally, and this module is where that boundary is drawn and labelled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ...errors import ConfigError, NotFoundError
from ..common import looks_like_object_id

if TYPE_CHECKING:
    from ..graph import GraphClient

# No `search`: $search is not supported on these collections, so offering it would be a
# promise Graph breaks. `contains` is honest about running locally.
MATCH_MODES = ["exact", "prefix", "contains"]

PACKAGE_COLUMNS = ["displayName", "isHidden", "id"]
CATALOG_COLUMNS = ["displayName", "catalogType", "state", "id"]


def match_option(func: Any) -> Any:
    """`--match`, with the modes entitlement management can actually honour."""
    return click.option(
        "--match",
        "match_mode",
        type=click.Choice(MATCH_MODES),
        default="exact",
        show_default=True,
        help="Match a display name: exact or prefix server-side, contains locally.",
    )(func)


def contains_filter(items: list[dict[str, Any]], needle: str | None) -> list[dict[str, Any]]:
    """Keep items whose displayName contains the needle, case-insensitively.

    Local, because `$search` does not exist on these collections and `contains()` is not
    an OData function Graph accepts here. Every page is fetched either way.
    """
    if not needle:
        return items
    wanted = needle.casefold()
    return [item for item in items if wanted in (item.get("displayName") or "").casefold()]


async def resolve_catalog_id(client: GraphClient, catalog: str) -> str:
    """Turn a catalog display name or ID into an ID, for use in a `catalog/id` filter.

    An ID is returned untouched. A name is resolved exactly, then by substring if that
    finds nothing, because catalog names are typed from memory and a single unambiguous
    substring match is almost certainly what was meant.
    """
    if looks_like_object_id(catalog):
        return catalog.strip()

    matches = await client.find_governance_by_display_name(
        "catalogs", catalog, mode="exact", select=("id", "displayName"), limit=2
    )
    if not matches:
        everything = [
            item async for item in client.list_governance("catalogs", select=("id", "displayName"))
        ]
        matches = contains_filter(everything, catalog)
    if not matches:
        raise NotFoundError(f"No catalog matched: {catalog}")
    if len(matches) > 1:
        raise ConfigError(
            f"{len(matches)} catalogs match '{catalog}'. Pass the catalog ID instead."
        )
    return str(matches[0]["id"])


async def find_matching(
    client: GraphClient,
    collection: str,
    identifier: str,
    *,
    noun: str,
    mode: str = "exact",
    select: tuple[str, ...] | None = None,
    expand: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Every entitlement management object matching an ID or a display name pattern.

    An object ID returns exactly one. A display name uses `eq` or `startswith`
    server-side, or fetches and filters locally for `contains`, since Graph offers no
    substring operator here.

    Several matches are returned rather than refused. `prefix` and `contains` are pattern
    modes, and a pattern matching more than one thing is the normal case, not an error:
    "show me the AWS packages" is a question with several answers. Callers that need
    exactly one object, such as the `--catalog` filter, use `resolve_catalog_id`.
    """
    if looks_like_object_id(identifier):
        return [
            await client.get_governance(
                collection, identifier.strip(), select=select, expand=expand
            )
        ]

    if mode == "contains":
        everything = [
            item async for item in client.list_governance(collection, select=select, expand=expand)
        ]
        matches = contains_filter(everything, identifier)
    else:
        matches = await client.find_governance_by_display_name(
            collection, identifier, mode=mode, select=select, expand=expand, limit=None
        )

    if not matches:
        hint = "" if mode == "contains" else " Try --match prefix or --match contains."
        raise NotFoundError(f"No {noun} matched: {identifier}.{hint}")
    return matches


def list_options(func: Any) -> Any:
    """Options shared by both list actions.

    No `--search`: `$search` is not supported on these collections. `--contains` is
    offered instead and filters locally, which the help text says plainly.
    """
    func = click.option(
        "--page-size",
        type=click.IntRange(1, 999),
        default=999,
        show_default=True,
        help="Graph $top page size.",
    )(func)
    func = click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N items.")(
        func
    )
    func = click.option(
        "--contains",
        metavar="TEXT",
        help="Keep items whose displayName contains TEXT. Filtered locally.",
    )(func)
    func = click.option(
        "--starts-with",
        metavar="PREFIX",
        help="Server-side startswith(displayName) filter.",
    )(func)
    func = click.option(
        "--name",
        metavar="TEXT",
        help="Server-side exact displayName match.",
    )(func)
    func = click.option(
        "--filter", "filter_expr", metavar="ODATA", help="Raw OData $filter expression."
    )(func)
    func = click.option(
        "--select", metavar="FIELDS", help="Comma-separated Graph fields to request."
    )(func)
    return func


def build_filter(filter_expr: str | None, name: str | None, starts_with: str | None) -> str | None:
    """Combine the filter shortcuts into one `$filter`, most explicit wins.

    A raw `--filter` is left alone: someone who wrote OData by hand means it.
    """
    from ..graph import escape_odata

    if filter_expr:
        return filter_expr
    if name:
        return f"displayName eq '{escape_odata(name)}'"
    if starts_with:
        return f"startswith(displayName,'{escape_odata(starts_with)}')"
    return None
