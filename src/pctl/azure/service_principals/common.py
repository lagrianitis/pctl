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


def looks_like_email(value: str) -> bool:
    """True when the value should be matched against a user's email, not their name.

    An `@` is enough: Entra ID display names do not contain one, and both the fields
    this then searches are addresses.
    """
    return "@" in value.strip()


async def _resolve_user_by_email(client: GraphClient, email: str) -> dict[str, Any]:
    """Resolve a user by userPrincipalName or mail.

    Both are checked because they routinely differ: a tenant may have a UPN of
    `lef@company.onmicrosoft.com` while mail is `lef@company.com`, and a user typing an
    address means whichever one they know.

    Matching is always exact here. There is no sensible prefix match on an address, and
    this path grants access, so guessing is not an option.
    """
    from ..graph import escape_odata

    literal = escape_odata(email.strip())
    matches = [
        item
        async for item in client.list_collection(
            "users",
            select=("id", "displayName", "userPrincipalName", "mail"),
            filter_expr=f"userPrincipalName eq '{literal}' or mail eq '{literal}'",
            limit=2,
        )
    ]
    if not matches:
        raise NotFoundError(
            f"No user has userPrincipalName or mail equal to: {email}. "
            "Check the address, or pass the object ID."
        )
    if len(matches) > 1:
        raise ConfigError(
            f"{len(matches)} users match the address '{email}'. "
            "Pass the object ID instead, so the wrong one cannot be chosen."
        )
    matches[0]["_resolved"] = "users"
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
    """Resolve an owner argument to a directory object.

    Three forms are accepted, distinguished without a flag:

    - a directory object GUID, used as-is
    - an email address (anything containing `@`), matched against a user's
      userPrincipalName or mail
    - a display name, matched against users and then service principals

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

    if looks_like_email(owner):
        if owner_type == "sp":
            raise ConfigError(
                f"'{owner}' looks like an email address, but --owner-type sp searches "
                "service principals, which have none. Drop --owner-type or use 'user'."
            )
        return await _resolve_user_by_email(client, owner)

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


def collect_owners(owners: tuple[str, ...], emails: str | None) -> list[str]:
    """Combine positional owners with a comma-separated `--emails` value.

    Order is preserved and duplicates dropped, so naming the same person twice costs one
    lookup rather than two and cannot produce two conflicting result rows.
    """
    collected = [owner.strip() for owner in owners if owner.strip()]
    if emails:
        collected.extend(part.strip() for part in emails.split(",") if part.strip())
    seen: dict[str, None] = {}
    for candidate in collected:
        seen.setdefault(candidate, None)
    return list(seen)


async def resolve_owners(
    client: GraphClient,
    wanted: list[str],
    *,
    mode: str = "exact",
    owner_type: str = "auto",
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Resolve several owner arguments concurrently.

    Returns the resolved objects and a list of `(argument, reason)` failures. Failures
    are collected rather than raised on the first one: with several owners, reporting
    them one run at a time would be tedious, and the caller decides whether a failure is
    fatal.
    """
    import asyncio

    async def one(candidate: str) -> dict[str, Any] | tuple[str, str]:
        try:
            return await resolve_owner(client, candidate, mode=mode, owner_type=owner_type)
        except (NotFoundError, ConfigError) as exc:
            return candidate, str(exc)

    results = await asyncio.gather(*[one(candidate) for candidate in wanted])
    resolved = [item for item in results if isinstance(item, dict)]
    failed = [item for item in results if isinstance(item, tuple)]
    return resolved, failed


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
