"""Action: `pctl azure apps add-client-secret`. Creates a client secret, and keeps its value.

Graph returns the value of a new client secret exactly once, in the response that creates
it. A command that created one and had nowhere to put the value would be a way to throw
credentials away, so everything here is arranged around not losing it: the destination is
checked before the secret exists, a missing destination is refused outright, and a failure
to store it removes the secret again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, NoReturn

import click

from ...config import AppContext
from ...errors import ConfigError, UpstreamError
from ...options import azure_options, output_options
from ...output import Renderer
from ...secrets import SecretObject
from .. import graph_client
from .common import (
    CREDENTIAL_SELECT,
    DEFAULT_SECRET_LIFETIME_DAYS,
    MAX_SECRET_LIFETIME_DAYS,
    CredentialKeys,
    app_options,
    credential_keys,
    ensure_name_unused,
    format_graph_time,
    match_option,
    require_one_app,
    resolve_app,
)
from .get_client_secrets import utcnow


@dataclass(slots=True, frozen=True)
class SecretRequest:
    """What was asked for: the new secret's name and end, and where its value should go."""

    name: str
    end: str
    target: SecretObject | None
    overwrite: bool
    show: bool


@click.command(name="add-client-secret")
@app_options
@click.option(
    "--name",
    required=True,
    metavar="NAME",
    help="Name for the new secret, shown as its description in the portal.",
)
@click.option(
    "--valid-for-days",
    "valid_days",
    type=click.IntRange(1, MAX_SECRET_LIFETIME_DAYS),
    default=DEFAULT_SECRET_LIFETIME_DAYS,
    show_default=True,
    metavar="DAYS",
    help="How long the secret is valid. The tenant's policy may allow less.",
)
@click.option(
    "--store-in",
    metavar="SECRET_ID",
    help="AWS Secrets Manager secret, by name or ARN, to add the new values to. It must "
    "already exist and hold a JSON object.",
)
@click.option(
    "--show-secret",
    is_flag=True,
    help="Also print the new value, once. Needed when there is no --store-in.",
)
@click.option("--overwrite", is_flag=True, help="Replace keys the --store-in secret already has.")
@azure_options
@match_option
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    app_name: str | None,
    app_id: str | None,
    name: str,
    valid_days: int,
    store_in: str | None,
    show_secret: bool,
    overwrite: bool,
    match_mode: str,
) -> None:
    """Create a client secret on an app registration, and store its value.

    Graph shows a new secret's value once and never again, so this refuses to run unless
    the value has somewhere to go: --store-in adds it to a Secrets Manager secret, and
    --show-secret prints it once. Either, or both.

    With --store-in, three keys are added to the JSON object held by that secret, named
    from the app and the secret, and every other key is kept:

    \b
      <app>_<name>_client_id         the app's appId
      <app>_<name>_client_secret     the new value
      <app>_<name>_client_exp_date   when it stops working, in UTC

    Names are lowercased and anything but letters and digits becomes an underscore, so
    app "Incident SCIM" and secret "terraform" give incident_scim_terraform_client_id.

    The destination is checked before the secret is created, and if storing fails after
    it was, the new secret is removed again. A name the app already uses is refused rather
    than adding a second secret. Reading the Secrets Manager secret needs
    secretsmanager:GetSecretValue and DescribeSecret; writing it needs PutSecretValue.

    \b
      pctl azure apps add-client-secret --app-name "Company Incident.io SCIM" \\
          --name terraform --store-in platform/app-credentials
      pctl azure apps add-client-secret --app-id 8f468c48-e9ac-4dd7-973d-9704b9cdd56d \\
          --name ci --valid-for-days 90 --show-secret
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    require_one_app(app_name, app_id)
    _require_destination(store_in, show_secret)
    target = _target(app, store_in)
    end = format_graph_time(utcnow() + timedelta(days=valid_days))
    request = SecretRequest(name, end, target, overwrite, show_secret)

    async def _run() -> dict[str, Any]:
        async with graph_client(app) as client:
            registration = await resolve_app(
                client, app_name, app_id, mode=match_mode, select=CREDENTIAL_SELECT
            )
            return await _create(client, registration, request)

    record = run(_run())
    with Renderer(app.output, single=True) as renderer:
        renderer.write(record)
    if not app.quiet:
        click.secho(f"Created client secret '{name}' on {record['app']}.", err=True, fg="green")


def _require_destination(store_in: str | None, show_secret: bool) -> None:
    """Refuse before anything is sent if the new value would have nowhere to go."""
    if store_in or show_secret:
        return
    raise ConfigError(
        "Refusing to create a client secret that would be lost: Graph shows its value only "
        "once. Pass --store-in SECRET_ID to keep it in Secrets Manager, or --show-secret to "
        "print it."
    )


def _target(app: AppContext, store_in: str | None) -> SecretObject | None:
    if not store_in:
        return None
    return SecretObject(store_in, app.creds.get("secret_region"), app.creds.get("profile"))


async def _create(
    client: Any, registration: dict[str, Any], request: SecretRequest
) -> dict[str, Any]:
    """Create the secret and put its value away, undoing the creation if that fails."""
    ensure_name_unused(registration, request.name)
    keys = credential_keys(str(registration.get("displayName")), request.name)
    if request.target is not None:
        request.target.check(keys.names(), overwrite=request.overwrite)
    created = await client.add_application_password(
        registration["id"], name=request.name, end_date_time=request.end
    )
    try:
        if not created.get("secretText"):
            raise UpstreamError("Graph created the secret but returned no value for it.")
        if request.target is not None:
            request.target.add(
                _stored_entries(keys, registration, created), overwrite=request.overwrite
            )
    except Exception as exc:
        await _roll_back(client, registration, created, exc)
    return _record(keys, registration, created, request)


def _stored_entries(
    keys: CredentialKeys, registration: dict[str, Any], created: dict[str, Any]
) -> dict[str, str]:
    return {
        keys.client_id: str(registration["appId"]),
        keys.client_secret: str(created["secretText"]),
        keys.client_exp_date: str(created.get("endDateTime") or ""),
    }


async def _roll_back(
    client: Any, registration: dict[str, Any], created: dict[str, Any], cause: Exception
) -> NoReturn:
    """Remove the secret that could not be stored, and always raise.

    A secret nobody holds is worse than no secret: it is live and nobody can use or revoke
    it by name. If even the removal fails, the message carries the key ID so it can be
    removed by hand.
    """
    key_id = created.get("keyId")
    try:
        await client.remove_application_password(registration["id"], key_id)
    except Exception as removal:
        raise UpstreamError(
            f"The new client secret (key ID {key_id}) could not be stored ({cause}) and could "
            f"not be removed again ({removal}). It is still valid and nobody holds its value: "
            "remove it in the portal."
        ) from cause
    raise UpstreamError(
        f"The new client secret could not be stored ({cause}), so it was removed again. "
        "Nothing was left behind."
    ) from cause


def _record(
    keys: CredentialKeys,
    registration: dict[str, Any],
    created: dict[str, Any],
    request: SecretRequest,
) -> dict[str, Any]:
    """What to report. The value is in it only when `--show-secret` asked for it."""
    stored = request.target is not None
    record: dict[str, Any] = {
        "app": registration.get("displayName"),
        "appId": registration.get("appId"),
        "name": request.name,
        "keyId": created.get("keyId"),
        "endDateTime": created.get("endDateTime"),
        "storedIn": request.target.secret_id if request.target else None,
        "storedKeys": keys.names() if stored else None,
    }
    if request.show:
        record["secret"] = created["secretText"]
    return record
