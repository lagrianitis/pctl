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
ASSIGNMENT_COLUMNS = [
    "targetDisplayName",
    "targetEmail",
    "accessPackageName",
    "state",
    "id",
]

# Graph's accessPackageAssignment states. Case matters in the $filter, so these are the
# exact spellings rather than lowercase choices normalised later.
ASSIGNMENT_STATES = [
    "Delivering",
    "PartiallyDelivered",
    "Delivered",
    "Expired",
    "DeliveryFailed",
]


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


async def resolve_governance_id(
    client: GraphClient, collection: str, identifier: str, *, noun: str
) -> str:
    """Turn a display name or ID into an ID, for use in a relationship filter.

    An ID is returned untouched. A name is resolved exactly, then by substring if that
    finds nothing, because these names are typed from memory and a single unambiguous
    substring match is almost certainly what was meant.

    Unlike `find_matching`, more than one result is refused. The answer becomes a scope in
    someone else's filter, and silently scoping a query to whichever match came first
    would give a confidently wrong result rather than an error.
    """
    if looks_like_object_id(identifier):
        return identifier.strip()

    matches = await client.find_governance_by_display_name(
        collection, identifier, mode="exact", select=("id", "displayName"), limit=2
    )
    if not matches:
        everything = [
            item async for item in client.list_governance(collection, select=("id", "displayName"))
        ]
        matches = contains_filter(everything, identifier)
    if not matches:
        raise NotFoundError(f"No {noun} matched: {identifier}")
    if len(matches) > 1:
        names = ", ".join(str(item.get("displayName")) for item in matches[:5])
        raise ConfigError(
            f"{len(matches)} {noun}s match '{identifier}' ({names}). Pass the ID instead."
        )
    return str(matches[0]["id"])


async def resolve_catalog_id(client: GraphClient, catalog: str) -> str:
    """Turn a catalog display name or ID into an ID, for a `catalog/id` filter."""
    return await resolve_governance_id(client, "catalogs", catalog, noun="catalog")


async def resolve_package_id(client: GraphClient, package: str) -> str:
    """Turn an access package display name or ID into an ID, for `accessPackage/id`."""
    return await resolve_governance_id(client, "accessPackages", package, noun="access package")


def flatten_assignment(item: dict[str, Any]) -> dict[str, Any]:
    """Lift the nested target and accessPackage names to the top level, in place.

    An assignment's interesting fields live one level down, under `target` and
    `accessPackage`, which a table or CSV column cannot address. The nested objects are
    left intact for json and ndjson consumers; these are additions, not replacements.
    """
    target = item.get("target") or {}
    package = item.get("accessPackage") or {}
    item["targetDisplayName"] = target.get("displayName")
    item["targetEmail"] = target.get("email") or target.get("principalName")
    item["targetId"] = target.get("objectId") or target.get("id")
    item["accessPackageName"] = package.get("displayName")
    item["accessPackageId"] = package.get("id")
    return item


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


# An assignment in one of these states is live or becoming live, so it blocks a fresh
# add. Expired and DeliveryFailed deliberately do not: neither is access.
ACTIVE_ASSIGNMENT_STATES = ("Delivered", "Delivering", "PartiallyDelivered")


def target_options(func: Any) -> Any:
    """The shared way to name one or more people for an assignment write."""
    func = click.option(
        "--ignore-missing",
        is_flag=True,
        help="Exit 0 even when a person could not be resolved.",
    )(func)
    func = click.option(
        "--emails",
        metavar="A@B,C@D",
        help="Comma-separated addresses, added to any given positionally.",
    )(func)
    return func


def collect_targets(targets: tuple[str, ...], emails: str | None) -> list[str]:
    """Combine positional identifiers with a comma-separated `--emails` value.

    Order is preserved and duplicates dropped, so naming someone twice costs one lookup
    and cannot produce two contradictory result rows.
    """
    collected = [item.strip() for item in targets if item.strip()]
    if emails:
        collected.extend(part.strip() for part in emails.split(",") if part.strip())
    seen: dict[str, None] = {}
    for candidate in collected:
        seen.setdefault(candidate, None)
    return list(seen)


async def resolve_policy_id(client: GraphClient, package_id: str, policy: str | None) -> str:
    """Choose the assignment policy an adminAdd request will name.

    An adminAdd must reference a policy, and a package can have several with different
    approval and expiry rules. So: an explicit `policy` wins; exactly one policy is used
    without asking; more than one is refused with the names listed, because picking
    arbitrarily would silently grant access under the wrong rules.
    """
    policies = [item async for item in client.list_assignment_policies(package_id)]
    if policy:
        if looks_like_object_id(policy):
            return policy.strip()
        wanted = policy.casefold()
        named = [item for item in policies if (item.get("displayName") or "").casefold() == wanted]
        if not named:
            available = ", ".join(str(item.get("displayName")) for item in policies) or "none"
            raise NotFoundError(
                f"No assignment policy named '{policy}' on this package. Available: {available}"
            )
        return str(named[0]["id"])

    if not policies:
        raise ConfigError(
            "This access package has no assignment policy, so an assignment cannot be "
            "created. Add a policy that allows direct assignment first."
        )
    if len(policies) > 1:
        available = ", ".join(str(item.get("displayName")) for item in policies)
        raise ConfigError(
            f"This access package has {len(policies)} assignment policies ({available}). "
            "Pass --policy to say which one should govern the assignment."
        )
    return str(policies[0]["id"])


def assignment_request(*, request_type: str, **assignment: str) -> dict[str, Any]:
    """Body for an accessPackageAssignmentRequest.

    The v1.0 property is `assignment`; beta called it `accessPackageAssignment`, and the
    request types are lower-camel here where beta capitalised them. A body copied from a
    beta example fails against v1.0, which is worth encoding once rather than rediscovering.
    """
    return {"requestType": request_type, "assignment": assignment}
