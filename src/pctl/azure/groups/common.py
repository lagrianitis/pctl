"""Code shared by the `groups` actions.

This lives beside `__init__.py` rather than inside it on purpose. Importing a
submodule binds it as an attribute of its parent package, so `groups/list.py`
would shadow the builtin `list` for any code whose globals are the package
namespace. Keeping runtime helpers in a plain module avoids that entirely.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import click

from ...errors import NotFoundError

if TYPE_CHECKING:
    from ..graph import GraphClient

MATCH_MODES = ["exact", "prefix", "search"]
DEFAULT_LIST_COLUMNS = ["displayName", "mail", "id"]
DEFAULT_MEMBER_COLUMNS = ["displayName", "userPrincipalName", "id"]


def match_option(func: Any) -> Any:
    """`--match`, shared by every action that resolves a display name."""
    return click.option(
        "--match",
        "match_mode",
        type=click.Choice(MATCH_MODES),
        default="exact",
        show_default=True,
        help="How to match the display name: exact, prefix or search (substring).",
    )(func)


async def resolve_one(
    client: GraphClient,
    name: str,
    *,
    mode: str,
    select: tuple[str, ...] = ("id", "displayName"),
) -> dict[str, Any]:
    """Resolve a display name to exactly one group, warning on ambiguity."""
    matches = await client.find_groups_by_display_name(name, mode=mode, select=select, limit=2)
    if not matches:
        raise NotFoundError(
            f"No group matched display name: {name}. Try --match prefix or --match search."
        )
    if len(matches) > 1:
        click.secho(
            f"{len(matches)} groups matched '{name}'; using {matches[0].get('id')}",
            err=True,
            fg="yellow",
        )
    return matches[0]


async def add_relations(
    client: GraphClient,
    group: dict[str, Any],
    *,
    members: bool = False,
    owners: bool = False,
    transitive: bool = False,
    counts: bool = False,
    member_limit: int | None = None,
) -> None:
    """Attach relations to a group in place, fetching all of them concurrently."""
    from ..graph import DEFAULT_MEMBER_SELECT

    group_id = group.get("id")
    if not group_id:
        return

    tasks: dict[str, Any] = {}
    if members:
        tasks["members"] = client.relation(
            group_id, "members", select=DEFAULT_MEMBER_SELECT, limit=member_limit
        )
    if owners:
        tasks["owners"] = client.relation(
            group_id, "owners", select=DEFAULT_MEMBER_SELECT, limit=member_limit
        )
    if transitive:
        tasks["transitiveMembers"] = client.relation(
            group_id, "transitiveMembers", select=DEFAULT_MEMBER_SELECT, limit=member_limit
        )
    if counts:
        tasks["memberCount"] = client.relation_count(group_id, "members")
        tasks["ownerCount"] = client.relation_count(group_id, "owners")

    if not tasks:
        return
    results = await asyncio.gather(*tasks.values())
    for key, value in zip(tasks, results, strict=True):
        group[key] = value
    # Derive counts for free when the relation was listed anyway.
    if members and isinstance(group.get("members"), list) and "memberCount" not in group:
        group["memberCount"] = len(group["members"])
    if owners and isinstance(group.get("owners"), list) and "ownerCount" not in group:
        group["ownerCount"] = len(group["owners"])
