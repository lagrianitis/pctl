"""Code shared by the `apps` actions.

An application registration and its service principal are two objects joined by `appId`,
with different `id` values. Nearly everything here exists to keep that straight, because
using one object's ID against the other's endpoint is the usual way this goes wrong.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import click

from ...errors import ConfigError, NotFoundError, UpstreamError
from ..common import MATCH_MODES, looks_like_object_id

if TYPE_CHECKING:
    from ..graph import GraphClient

DEFAULT_LIST_COLUMNS = ["displayName", "appId", "signInAudience", "id"]
CREDENTIAL_SELECT = ("id", "appId", "displayName", "passwordCredentials", "keyCredentials")
DEFAULT_CREDENTIAL_COLUMNS = ["type", "name", "status", "daysRemaining", "endDateTime", "keyId"]
DEFAULT_EXPIRY_WINDOW_DAYS = 30
SECONDS_PER_DAY = 86_400
STATUS_VALID = "valid"
STATUS_EXPIRING = "expiring"
STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"
ATTENTION_STATUSES = (STATUS_EXPIRED, STATUS_EXPIRING)
DEFAULT_SECRET_LIFETIME_DAYS = 180
MAX_SECRET_LIFETIME_DAYS = 365
_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


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


def app_options(func: Any) -> Any:
    """`--app-name` and `--app-id`: two separate ways to name one app registration.

    Separate flags rather than one that guesses, so `--app-id` can skip the display name
    search altogether. Pair with `require_one_app` and `resolve_app`.
    """
    func = click.option(
        "--app-id",
        metavar="APPID",
        help="appId (Application (client) ID) of the app registration. Skips the display "
        "name search, so it is the exact and cheaper way to name the app.",
    )(func)
    return click.option(
        "--app-name",
        metavar="NAME",
        help="Display name of the app registration. Use this or --app-id.",
    )(func)


def require_one_app(app_name: str | None, app_id: str | None) -> None:
    """Exactly one of the two ways to name the app, checked before anything is sent."""
    if bool(app_name) == bool(app_id):
        raise ConfigError("Pass exactly one of --app-name or --app-id.")


async def resolve_app(
    client: GraphClient,
    app_name: str | None,
    app_id: str | None,
    *,
    mode: str = "exact",
    select: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Find the app by appId when given, which needs no display name search."""
    if app_id:
        return await resolve_by_app_id(client, app_id, select=select)
    return await resolve_by_display_name(
        client, str(app_name), mode=mode, select=select, instead="--app-id"
    )


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

    return await resolve_by_display_name(client, identifier, mode=mode, select=select)


async def resolve_by_display_name(
    client: GraphClient,
    display_name: str,
    *,
    mode: str = "exact",
    select: tuple[str, ...] | None = None,
    instead: str = "the appId",
) -> dict[str, Any]:
    """Resolve an application from its display name, and only that.

    Unlike `resolve_application` this never reads the value as a GUID, for a command that
    takes the name and the appId as separate flags. `instead` names what to pass in place
    of the name, so the advice matches the flags the command actually has.
    """
    matches = await client.find_applications_by_display_name(
        display_name, mode=mode, select=select, limit=2
    )
    if not matches:
        raise NotFoundError(
            f"No application registration matched display name: {display_name}. "
            f"Try --match search, or pass {instead}."
        )
    if len(matches) > 1:
        raise ConfigError(
            f"{len(matches)} application registrations match '{display_name}'. "
            f"Pass {instead} instead, so the wrong one cannot be chosen."
        )
    return matches[0]


async def resolve_by_app_id(
    client: GraphClient, app_id: str, *, select: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Resolve an application from its appId, with no display name search at all."""
    if not looks_like_object_id(app_id):
        raise ConfigError(f"--app-id must be a GUID, the Application (client) ID: {app_id}")
    found = await client.find_application_by_app_id(app_id.strip(), select=select)
    if found is None:
        raise NotFoundError(f"No application has appId {app_id.strip()}.")
    return found


def parse_graph_time(value: str | None) -> datetime | None:
    """A Graph timestamp as an aware datetime, or None when it is absent or unreadable.

    Graph sends UTC in ISO 8601 and may give seven fractional digits, which
    `datetime.fromisoformat` accepts on Python 3.11 and later. A value with no zone is
    taken to be UTC, since that is what Graph means by it.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def credential_rows(registration: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per client secret and per certificate, soonest to expire first.

    Each row is built field by field rather than copied from Graph. That is a safeguard,
    not tidiness: a response can carry a secret value or a certificate's key material, and
    a row that copies whatever arrived would print it. A credential with no end date sorts
    last, where it is least likely to be mistaken for the one about to lapse.
    """
    rows = [
        *(
            _credential_row(registration, item, "secret")
            for item in _entries(registration, "passwordCredentials")
        ),
        *(
            _credential_row(registration, item, "certificate")
            for item in _entries(registration, "keyCredentials")
        ),
    ]
    return sorted(rows, key=_by_expiry)


def _entries(registration: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    """A credential collection, tolerating one that is absent or null."""
    return registration.get(collection) or []


def _credential_row(
    registration: dict[str, Any], item: dict[str, Any], kind: str
) -> dict[str, Any]:
    return {
        "app": registration.get("displayName"),
        "appId": registration.get("appId"),
        "type": kind,
        "name": item.get("displayName"),
        "keyId": item.get("keyId"),
        "startDateTime": item.get("startDateTime"),
        "endDateTime": item.get("endDateTime"),
        "hint": item.get("hint") if kind == "secret" else None,
    }


def _by_expiry(row: dict[str, Any]) -> tuple[bool, datetime]:
    end = parse_graph_time(row["endDateTime"])
    return end is None, end or datetime.min.replace(tzinfo=UTC)


def credential_status(end: datetime | None, now: datetime, window: timedelta) -> str:
    """Whether a credential has lapsed, is about to, or is comfortably in date.

    The moment is a parameter, not read from the clock, so a test can sit exactly on each
    boundary. A credential ending at this very instant has lapsed, and one ending exactly
    `window` from now is still expiring: the window is inclusive, the deadline is not.
    """
    if end is None:
        return STATUS_UNKNOWN
    remaining = end - now
    if remaining <= timedelta(0):
        return STATUS_EXPIRED
    if remaining <= window:
        return STATUS_EXPIRING
    return STATUS_VALID


def days_remaining(end: datetime | None, now: datetime) -> int | None:
    """Whole days left, rounded down, and negative once the end date has passed.

    Zero therefore means less than a day left, or just lapsed. It is rounded down so that a
    credential never looks as if it has longer than it does.
    """
    if end is None:
        return None
    return math.floor((end - now).total_seconds() / SECONDS_PER_DAY)


def with_expiry(
    rows: list[dict[str, Any]], now: datetime, window: timedelta
) -> list[dict[str, Any]]:
    """The rows with `daysRemaining` and `status` added, leaving the originals untouched."""
    annotated = []
    for row in rows:
        end = parse_graph_time(row["endDateTime"])
        annotated.append(
            {
                **row,
                "daysRemaining": days_remaining(end, now),
                "status": credential_status(end, now, window),
            }
        )
    return annotated


@dataclass(slots=True, frozen=True)
class CredentialKeys:
    """The three keys a new client secret is stored under in a Secrets Manager secret."""

    client_id: str
    client_secret: str
    client_exp_date: str

    def names(self) -> list[str]:
        return [self.client_id, self.client_secret, self.client_exp_date]


def key_slug(text: str) -> str:
    """Lowercase, with every run of other characters collapsed to one underscore."""
    return _NOT_ALPHANUMERIC.sub("_", text.casefold()).strip("_")


def credential_keys(app_name: str, secret_name: str) -> CredentialKeys:
    """`<app>_<secret>_client_id`, `_client_secret` and `_client_exp_date`.

    Both names are reduced to letters and digits, so `Incident SCIM` and `terraform` give
    `incident_scim_terraform_client_id`. A name with nothing left once reduced would make
    keys that start with a bare underscore and could collide with any other, so it is
    refused.
    """
    app, secret = key_slug(app_name), key_slug(secret_name)
    if not app or not secret:
        raise ConfigError(
            f"Cannot build key names from app '{app_name}' and secret name '{secret_name}': "
            "each needs at least one letter or digit."
        )
    prefix = f"{app}_{secret}"
    return CredentialKeys(
        client_id=f"{prefix}_client_id",
        client_secret=f"{prefix}_client_secret",
        client_exp_date=f"{prefix}_client_exp_date",
    )


def ensure_name_unused(registration: dict[str, Any], name: str) -> None:
    """Refuse a secret name the app already uses.

    Creating a secret is not idempotent, so running a pipeline twice would otherwise add a
    second live secret under the same name, with only one of them known. A name the
    portal calls a description is not unique to Graph, which is why this is checked here.
    """
    wanted = name.casefold()
    for item in _entries(registration, "passwordCredentials"):
        if str(item.get("displayName") or "").casefold() == wanted:
            raise ConfigError(
                f"{registration.get('displayName')} already has a client secret named "
                f"'{name}'. Choose another name; creating it again would add a second one."
            )


def find_secret(registration: dict[str, Any], key_id: str) -> dict[str, Any]:
    """The one client secret with this key ID.

    Only the key ID, never the name: names are not unique, and removal cannot be undone,
    so nothing here is ever a choice between several.
    """
    wanted = key_id.strip().casefold()
    for item in _entries(registration, "passwordCredentials"):
        if str(item.get("keyId") or "").casefold() == wanted:
            return item
    app = registration.get("displayName")
    certificates = _entries(registration, "keyCredentials")
    if any(str(item.get("keyId") or "").casefold() == wanted for item in certificates):
        raise ConfigError(
            f"Key ID {key_id} on {app} is a certificate. Only client secrets can be removed here."
        )
    raise NotFoundError(f"{app} has no client secret with key ID {key_id}.")


def requires_force(secret: dict[str, Any], now: datetime, window: timedelta) -> bool:
    """Whether removing this secret needs `--force`: it is still comfortably in date.

    A secret that has lapsed or is within the window of lapsing is the ordinary thing to
    clean up. One with a long time left, or with no end date to judge by, may well still be
    in use, so removing it has to be asked for outright.
    """
    status = credential_status(parse_graph_time(secret.get("endDateTime")), now, window)
    return status in (STATUS_VALID, STATUS_UNKNOWN)


def format_graph_time(moment: datetime) -> str:
    """A UTC moment in the form Graph takes and returns: ISO 8601 with a trailing Z."""
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
