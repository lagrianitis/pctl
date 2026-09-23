"""Code shared by the `apps` actions.

An application registration and its service principal are two objects joined by `appId`,
with different `id` values. Nearly everything here exists to keep that straight, because
using one object's ID against the other's endpoint is the usual way this goes wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

from ...errors import ConfigError, NotFoundError, UpstreamError
from ..common import MATCH_MODES, looks_like_object_id

if TYPE_CHECKING:
    from ..graph import GraphClient

DEFAULT_LIST_COLUMNS = ["displayName", "appId", "signInAudience", "id"]


def match_option(func: Any) -> Any:
    """`--match`, used when the argument is a display name rather than a GUID."""
    return click.option(
        "--match",
        "match_mode",
        type=click.Choice(MATCH_MODES),
        default="exact",
        show_default=True,
        help="How to match a display name: exact, prefix or search (substring).",
    )(func)


async def resolve_application(
    client: GraphClient,
    identifier: str,
    *,
    mode: str = "exact",
    select: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Resolve an application from an appId, an object ID, or a display name.

    A bare GUID is tried as an `appId` first and only then as a directory object ID. That
    order is deliberate: the portal's overview page shows the appId as "Application
    (client) ID" and it is what people copy, while the object ID is comparatively hidden.

    An ambiguous display name is refused rather than resolved to the first match, since a
    tenant routinely holds several registrations with similar names.
    """
    if looks_like_object_id(identifier):
        guid = identifier.strip()
        by_app_id = await client.find_application_by_app_id(guid, select=select)
        if by_app_id is not None:
            return by_app_id
        try:
            return await client.get_application(guid, select=select)
        except UpstreamError as exc:
            # A GUID that is neither an appId nor an object ID gives a 404 here, which is
            # a lookup miss rather than an upstream fault, so it is reported as exit 4.
            raise NotFoundError(
                f"No application has appId or object ID {guid}. "
                "Check which of the two GUIDs you have."
            ) from exc

    matches = await client.find_applications_by_display_name(
        identifier, mode=mode, select=select, limit=2
    )
    if not matches:
        raise NotFoundError(
            f"No application registration matched display name: {identifier}. "
            "Try --match search, or pass the appId."
        )
    if len(matches) > 1:
        raise ConfigError(
            f"{len(matches)} application registrations match '{identifier}'. "
            "Pass the appId instead, so the wrong one cannot be chosen."
        )
    return matches[0]
