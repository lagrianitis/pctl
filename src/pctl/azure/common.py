"""Code shared by every service in the `azure` case.

Directory lookups live here rather than in a service package because more than one
service needs them: `sp` resolves an owner to a user, and `users` resolves the same
thing as its whole purpose. Keeping one implementation means an address matched one way
in one command cannot be matched differently in another.

Beside `__init__.py` rather than inside it, for the reason `groups/common.py` gives:
importing a submodule binds it as an attribute of its parent package, and a package
namespace is a poor place for runtime helpers.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..errors import ConfigError, NotFoundError

if TYPE_CHECKING:
    from .graph import GraphClient

_OBJECT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

MATCH_MODES = ["exact", "prefix", "search"]


def looks_like_object_id(value: str) -> bool:
    """True when the value is already a directory object GUID.

    Lets an argument take a name or an object ID without a flag to say which. A GUID is
    unambiguous: no Entra ID display name is a bare GUID in canonical form, so guessing
    here cannot misfire. `fullmatch`, so a name that merely contains a GUID is still
    treated as a name.
    """
    return bool(_OBJECT_ID.fullmatch(value.strip()))


def looks_like_email(value: str) -> bool:
    """True when the value should be matched against an address, not a display name.

    An `@` is enough: Entra ID display names do not contain one, and both fields this
    then searches are addresses.
    """
    return "@" in value.strip()


async def find_users_by_address(
    client: GraphClient,
    address: str,
    *,
    select: tuple[str, ...],
    limit: int | None = 2,
) -> list[dict[str, Any]]:
    """Users whose userPrincipalName or mail equals the address.

    Both are checked because they routinely differ: a tenant may have a UPN of
    `lef@company.onmicrosoft.com` while mail is `lef@company.com`, and someone typing an
    address means whichever one they know.

    Always an exact comparison. There is no sensible prefix match on an address.
    """
    from .graph import escape_odata

    literal = escape_odata(address.strip())
    return [
        item
        async for item in client.list_collection(
            "users",
            select=select,
            filter_expr=f"userPrincipalName eq '{literal}' or mail eq '{literal}'",
            limit=limit,
        )
    ]


async def find_user(
    client: GraphClient,
    identifier: str,
    *,
    select: tuple[str, ...],
    mode: str = "exact",
) -> dict[str, Any]:
    """Resolve one user from an object ID, an email address, or a display name.

    Which form was given is inferred rather than declared, so callers do not need a flag
    for something that is obvious from the value.

    An ambiguous result is refused rather than resolved to the first match. Two people
    can share a display name, and every caller of this is about to act on the answer.
    """
    if looks_like_object_id(identifier):
        return await client.get_user(identifier.strip(), select=select)

    if looks_like_email(identifier):
        matches = await find_users_by_address(client, identifier, select=select)
        described = "userPrincipalName or mail"
    else:
        matches = await client.find_by_display_name(
            "users", identifier, mode=mode, select=select, limit=2
        )
        described = f"displayName ({mode})"

    if not matches:
        raise NotFoundError(
            f"No user matched {described}: {identifier}. "
            "Try an email address, --match search, or the object ID."
        )
    if len(matches) > 1:
        raise ConfigError(
            f"{len(matches)} users match '{identifier}'. "
            "Use the email address or the object ID, so the wrong one cannot be chosen."
        )
    return matches[0]
