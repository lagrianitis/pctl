"""Code shared by the `sp` actions.

Beside `__init__.py` rather than inside it, for the same reason as `groups/common.py`:
importing a submodule binds it as an attribute of its parent package, so
`service_principals/list.py` would shadow the builtin `list` for any code whose globals
are the package namespace.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import click

from ...errors import ConfigError, NotFoundError

if TYPE_CHECKING:
    from ..graph import GraphClient

_OBJECT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
OWNER_TYPES = ["auto", "user", "sp"]

MATCH_MODES = ["exact", "prefix", "search"]
# Deliberately not the same vocabulary as MATCH_MODES above. `search` means Graph's
# server-side $search everywhere else in this CLI, and this filter runs locally, so
# calling the substring mode `contains` avoids implying a round trip that never happens.
PRINCIPAL_MATCH_MODES = ["exact", "prefix", "contains"]
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


def looks_like_object_id(value: str) -> bool:
    """True when the value is already a directory object GUID.

    Lets the owner arguments take either a display name or an object ID without a flag
    to say which. A GUID is unambiguous: no Entra ID display name is a bare GUID in
    canonical form, so guessing here cannot misfire.
    """
    return bool(_OBJECT_ID.fullmatch(value.strip()))


async def resolve_owner(
    client: GraphClient,
    owner: str,
    *,
    mode: str = "exact",
    owner_type: str = "auto",
) -> dict[str, Any]:
    """Resolve an owner argument to a directory object, by GUID or display name.

    Only users and service principals can own a service principal, so groups are not
    searched: resolving one would yield a valid-looking GUID that Graph then rejects.

    `owner_type` of `auto` tries users first, since a human owner is the common case,
    and falls back to service principals. Pass `user` or `sp` to skip the fallback when
    a name exists in both collections.
    """
    if looks_like_object_id(owner):
        return {"id": owner.strip(), "displayName": owner.strip(), "_resolved": "object-id"}

    collections = {
        "auto": ("users", "servicePrincipals"),
        "user": ("users",),
        "sp": ("servicePrincipals",),
    }
    if owner_type not in collections:
        raise ValueError(f"unknown owner type: {owner_type}")

    for collection in collections[owner_type]:
        matches = await client.find_by_display_name(
            collection,
            owner,
            mode=mode,
            select=("id", "displayName", "userPrincipalName"),
            limit=2,
        )
        if not matches:
            continue
        if len(matches) > 1:
            raise ConfigError(
                f"{len(matches)} objects in {collection} match '{owner}'. "
                "Pass the object ID instead, so the wrong one cannot be chosen."
            )
        matches[0]["_resolved"] = collection
        return matches[0]

    searched = " or ".join(collections[owner_type])
    raise NotFoundError(
        f"No {searched} entry matched: {owner}. Only users and service principals can "
        "own a service principal, so groups are not searched."
    )


def owner_label(owner: dict[str, Any]) -> str:
    """A short, unambiguous description of a resolved owner, for log and info lines."""
    name = owner.get("displayName") or owner.get("userPrincipalName") or owner["id"]
    if owner.get("_resolved") == "object-id":
        return f"object {owner['id']}"
    return f"{name} ({owner['id']})"


def filter_by_principal(
    assignments: list[dict[str, Any]],
    principal: str | None,
    *,
    mode: str = "exact",
) -> list[dict[str, Any]]:
    """Keep assignments whose principalDisplayName matches, case-insensitively.

    No `principal` means no filtering, so every assignment is returned.

    `mode` is `exact` (the whole name), `prefix` (`startswith`) or `contains`
    (substring). `exact` is the default because the common use is an access check, and
    a loose match there would answer a question nobody asked: `Platform` matching
    `AWS Platform Admins` would report access that a specific group may not have.

    Filtered here rather than server-side because Graph does not support `$filter` on
    `principalDisplayName` for these relations. The whole collection is paged either
    way, so this only narrows what gets rendered.
    """
    if not principal:
        return assignments
    wanted = principal.casefold()

    def matches(item: dict[str, Any]) -> bool:
        actual = (item.get("principalDisplayName") or "").casefold()
        match mode:
            case "exact":
                return actual == wanted
            case "prefix":
                return actual.startswith(wanted)
            case "contains":
                return wanted in actual
            case _:
                raise ValueError(f"unknown principal match mode: {mode}")

    return [item for item in assignments if matches(item)]


def label_roles(assignments: list[dict[str, Any]], role_names: dict[str, str]) -> None:
    """Add `appRoleName` to each assignment in place, resolving the GUID."""
    for item in assignments:
        role_id = item.get("appRoleId")
        if role_id:
            item["appRoleName"] = role_names.get(role_id, role_id)
