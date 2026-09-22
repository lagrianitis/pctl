"""Code shared by the `sp` actions.

Beside `__init__.py` rather than inside it, for the same reason as `groups/common.py`:
importing a submodule binds it as an attribute of its parent package, so
`service_principals/list.py` would shadow the builtin `list` for any code whose globals
are the package namespace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ...errors import NotFoundError

if TYPE_CHECKING:
    from ..graph import GraphClient

MATCH_MODES = ["exact", "prefix", "search"]
DEFAULT_LIST_COLUMNS = ["displayName", "appId", "servicePrincipalType", "id"]


def match_option(func: Any) -> Any:
    """`--match`, shared by every action that resolves a display name."""
    return click.option(
        "--match",
        "match_mode",
        type=click.Choice(MATCH_MODES),
        default="search",
        show_default=True,
        help="How to match the display name: exact, prefix or search (substring).",
    )(func)


async def resolve_one(
    client: GraphClient,
    name: str,
    *,
    mode: str,
    select: tuple[str, ...] = ("id", "displayName", "appId"),
) -> dict[str, Any]:
    """Resolve a display name to exactly one service principal, warning on ambiguity.

    Ambiguity is more likely here than with groups: a single application often has both
    an application object and a service principal sharing a display name, and tenants
    accumulate similarly named apps. So the warning names the appId, which is what
    distinguishes them.
    """
    matches = await client.find_service_principals_by_display_name(
        name, mode=mode, select=select, limit=2
    )
    if not matches:
        raise NotFoundError(
            f"No service principal matched display name: {name}. "
            "Try --match prefix, or a shorter --match search term."
        )
    if len(matches) > 1:
        click.secho(
            f"{len(matches)} service principals matched '{name}'; using "
            f"{matches[0].get('displayName')} (appId {matches[0].get('appId')})",
            err=True,
            fg="yellow",
        )
    return matches[0]


def filter_by_principal(
    assignments: list[dict[str, Any]], principal: str | None
) -> list[dict[str, Any]]:
    """Keep assignments whose principalDisplayName matches, case-insensitively.

    Filtered here rather than server-side because Graph does not support `$filter` on
    `principalDisplayName` for these relations. The whole collection is paged either
    way, so this only narrows what gets rendered.
    """
    if not principal:
        return assignments
    wanted = principal.casefold()
    return [
        item
        for item in assignments
        if (item.get("principalDisplayName") or "").casefold() == wanted
    ]


def label_roles(assignments: list[dict[str, Any]], role_names: dict[str, str]) -> None:
    """Add `appRoleName` to each assignment in place, resolving the GUID."""
    for item in assignments:
        role_id = item.get("appRoleId")
        if role_id:
            item["appRoleName"] = role_names.get(role_id, role_id)
