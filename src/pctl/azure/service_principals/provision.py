"""Action: `pctl azure sp provision`.

On-demand provisioning, the "Provision on demand" button in the portal. Everything
specific to it lives here rather than in `common.py`, because no other action needs it:
the job and rule lookups, the subject shapes, and the verdict that Graph buries inside a
JSON string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import click

from ...config import AppContext
from ...errors import ConfigError, NotFoundError, UpstreamError
from ...options import azure_options, output_options
from ...output import Renderer, summarise
from .. import graph_client
from ..common import find_user, looks_like_object_id
from .common import match_option, resolve_one

if TYPE_CHECKING:
    from ..graph import GraphClient

RESULT_COLUMNS = [
    "servicePrincipal",
    "subject",
    "subjectId",
    "subjectType",
    "outcome",
    "detail",
]
USER_FIELDS = ("id", "displayName", "userPrincipalName", "mail")

# Graph reports "Skipped" both for a subject that is already in sync and for one it
# declined to provision, so the reason decides whether the run succeeded. RedundantExport
# means source and target already match, which is the on-demand equivalent of a no-op.
# Every other skip reason — out of scope, not assigned, filtered — means no provisioning
# happened, and reporting that as success would be the worst possible lie here.
BENIGN_SKIP_CODES = frozenset({"redundantexport"})


@dataclass(frozen=True, slots=True)
class ProvisioningTarget:
    """Where a provisioning request goes, resolved once and reused for every subject.

    Grouped rather than threaded through as four parameters, and frozen because resolving
    the job or rule differently partway through a batch would make the result rows
    incomparable.
    """

    sp_id: str
    job_id: str
    rule_id: str
    label: str


@click.command(name="provision")
@click.option(
    "--app",
    "name",
    required=True,
    metavar="NAME|ID",
    help="The Enterprise Application to provision through. Display name or ID.",
)
@click.option(
    "--group",
    "groups",
    multiple=True,
    metavar="NAME|ID",
    help="Group to provision. Repeat for several.",
)
@click.option(
    "--user",
    "users",
    multiple=True,
    metavar="EMAIL|NAME|ID",
    help="User to provision. Repeat for several.",
)
@azure_options
@match_option
@click.option(
    "--job",
    "job_id",
    metavar="ID",
    help="Synchronization job. Needed only when the application has more than one.",
)
@click.option(
    "--rule",
    "rule_id",
    metavar="ID",
    help="Synchronization rule. Needed only when the job's schema has more than one.",
)
@click.option(
    "--ignore-missing",
    is_flag=True,
    help="Exit 0 even when a subject could not be resolved.",
)
@output_options
@click.pass_context
def command(
    ctx: click.Context,
    name: str,
    groups: tuple[str, ...],
    users: tuple[str, ...],
    match_mode: str,
    job_id: str | None,
    rule_id: str | None,
    ignore_missing: bool,
) -> None:
    """Provision users or groups into an application now, without waiting for the cycle.

    Entra ID provisioning normally runs on a 40-minute cycle. This is the "Provision on
    demand" action: it pushes named subjects through the connector immediately, which is
    what you want after fixing a mapping or when someone needs access today.

    Only applications with provisioning configured have a synchronization job. If the
    application has none, this says so rather than failing obscurely. With exactly one job
    and one rule neither has to be named; more than one and the command lists them and
    asks, because provisioning through the wrong rule writes the wrong attributes.

    A 200 from Graph does not mean a subject was provisioned. The verdict is reported per
    subject as `applied`, `already-in-sync` or `failed`, and anything that did not
    provision exits 5. A subject that is out of scope or unassigned comes back as a skip,
    which counts as a failure here: nothing was provisioned.

    Subjects are sent one at a time. Graph rate limits this action to 5 requests every 10
    seconds, so a concurrent batch would simply be throttled.

    Requires Synchronization.ReadWrite.All.

    \b
      pctl azure sp provision --app "$APP" --group "AWS Platform Admins"
      pctl azure sp provision --app "$APP" --user ann@company.com
      pctl azure sp provision --app "$APP" --group "Team A" --group "Team B"
      pctl azure sp provision --app "$APP" --user ann@company.com --group "Team A" -o json
      pctl azure sp provision --app "$APP" --group "Team A" --job "$JOB" --rule "$RULE"
    """
    from ..graph import run

    app = ctx.ensure_object(AppContext)
    if not groups and not users:
        raise click.UsageError("Provide at least one subject with --group or --user.")

    async def _run() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        async with graph_client(app) as client:
            found = await resolve_one(client, name, mode=match_mode)
            sp_id = str(found["id"])
            job = job_id or await resolve_job_id(client, sp_id)
            target = ProvisioningTarget(
                sp_id=sp_id,
                job_id=job,
                rule_id=rule_id or await resolve_rule_id(client, sp_id, job),
                label=str(found.get("displayName") or sp_id),
            )
            app.log(f"provisioning through {target.label} job={job} rule={target.rule_id}")

            subjects, failed = await resolve_subjects(client, groups, users)
            records: list[dict[str, Any]] = []
            for subject in subjects:
                # Sequential on purpose: Graph allows 5 of these every 10 seconds.
                records.append(await provision_one(client, target, subject))
            return records, failed

    records, failed = run(_run())

    with Renderer(app.output, columns=RESULT_COLUMNS) as renderer:
        renderer.write_all(records)

    report(records, failed, quiet=app.quiet)
    if failed and not ignore_missing:
        raise NotFoundError(
            f"{len(failed)} subject(s) could not be resolved. "
            "Pass an object ID, or use --ignore-missing to tolerate it."
        )
    unprovisioned = [record for record in records if record["outcome"] == "failed"]
    if unprovisioned:
        raise UpstreamError(
            f"{len(unprovisioned)} of {len(records)} subject(s) were not provisioned: "
            + ", ".join(f"{record['subject']} [{record['detail']}]" for record in unprovisioned)
        )


async def resolve_job_id(client: GraphClient, sp_id: str) -> str:
    """The synchronization job to provision through, when one was not named.

    No job means provisioning was never configured, which is a configuration problem the
    caller can act on. Several jobs are refused rather than guessed: a tenant with both an
    inbound and an outbound job would otherwise provision in whichever direction happened
    to come back first.
    """
    jobs = await client.synchronization_jobs(sp_id)
    if not jobs:
        raise ConfigError(
            "This application has no synchronization job, so provisioning is not enabled "
            "for it. Configure provisioning in the portal first."
        )
    if len(jobs) > 1:
        available = ", ".join(f"{job.get('id')} ({job.get('templateId')})" for job in jobs)
        raise ConfigError(
            f"This application has {len(jobs)} synchronization jobs ({available}). "
            "Pass --job to say which one should provision."
        )
    return str(jobs[0]["id"])


async def resolve_rule_id(client: GraphClient, sp_id: str, job_id: str) -> str:
    """The synchronization rule to run, when one was not named.

    Rule IDs are not plain GUIDs: a versioned rule looks like `<guid>#V2`, so they are
    passed through as strings rather than validated as object IDs.
    """
    rules = await client.synchronization_rules(sp_id, job_id)
    if not rules:
        raise ConfigError(
            f"Synchronization job {job_id} has no rules in its schema, so there is "
            "nothing to provision through."
        )
    if len(rules) > 1:
        available = ", ".join(
            f"{rule.get('id')} ({rule.get('sourceDirectoryName')} -> "
            f"{rule.get('targetDirectoryName')})"
            for rule in rules
        )
        raise ConfigError(
            f"This job's schema has {len(rules)} synchronization rules ({available}). "
            "Pass --rule to say which one should run."
        )
    return str(rules[0]["id"])


async def resolve_subjects(
    client: GraphClient, groups: tuple[str, ...], users: tuple[str, ...]
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Turn the --group and --user values into provisioning subjects.

    Returns the resolved subjects and a list of `(argument, reason)` failures, so one bad
    name does not cost the whole batch. Resolution is concurrent; only the provisioning
    calls themselves are serialised.

    `objectTypeName` is the capitalised `User`/`Group` that Graph expects when
    provisioning from Entra ID to an application. The lowercase spellings belong to Entra
    Cloud Sync, which reads subjects out of Active Directory by distinguished name.
    """
    import asyncio

    async def one(value: str, kind: str) -> dict[str, str] | tuple[str, str]:
        try:
            resolved = await (
                resolve_group(client, value)
                if kind == "Group"
                else resolve_subject_user(client, value)
            )
        except (NotFoundError, ConfigError) as exc:
            return value, str(exc)
        return {**resolved, "objectTypeName": kind}

    wanted = [(value, "Group") for value in dedupe(groups)]
    wanted += [(value, "User") for value in dedupe(users)]
    results = await asyncio.gather(*[one(value, kind) for value, kind in wanted])
    return (
        [item for item in results if isinstance(item, dict)],
        [item for item in results if isinstance(item, tuple)],
    )


def dedupe(values: tuple[str, ...]) -> list[str]:
    """Order-preserving deduplication, so naming a subject twice provisions it once."""
    seen: dict[str, None] = {}
    for value in values:
        if value.strip():
            seen.setdefault(value.strip(), None)
    return list(seen)


async def resolve_group(client: GraphClient, value: str) -> dict[str, str]:
    """Resolve a group to an object ID, refusing an ambiguous display name.

    Deliberately stricter than `groups get`, which warns and takes the first match. This
    is a write into a downstream system, so provisioning the wrong group is not something
    a warning on stderr makes acceptable.
    """
    if looks_like_object_id(value):
        return {"objectId": value.strip(), "displayName": value.strip()}
    matches = await client.find_by_display_name(
        "groups", value, mode="exact", select=("id", "displayName"), limit=2
    )
    if not matches:
        raise NotFoundError(f"No group matched display name: {value}")
    if len(matches) > 1:
        raise ConfigError(
            f"{len(matches)} groups match '{value}'. Pass the object ID instead, so the "
            "wrong one cannot be provisioned."
        )
    return {
        "objectId": str(matches[0]["id"]),
        "displayName": str(matches[0].get("displayName")),
    }


async def resolve_subject_user(client: GraphClient, value: str) -> dict[str, str]:
    """Resolve a user to an object ID, by address, display name or ID."""
    found = await find_user(client, value, select=USER_FIELDS)
    label = found.get("displayName") or found.get("userPrincipalName") or found["id"]
    return {"objectId": str(found["id"]), "displayName": str(label)}


async def provision_one(
    client: GraphClient, target: ProvisioningTarget, subject: dict[str, str]
) -> dict[str, Any]:
    """Provision a single subject and describe what Graph decided.

    One request per subject rather than one for the batch. `subjects` is a collection, but
    the response carries a single verdict, so batching would report one result for several
    people and lose the attribution that makes this command useful.
    """
    body = {
        "parameters": [
            {
                "ruleId": target.rule_id,
                "subjects": [
                    {
                        "objectId": subject["objectId"],
                        "objectTypeName": subject["objectTypeName"],
                    }
                ],
            }
        ]
    }
    payload = await client.provision_on_demand(target.sp_id, target.job_id, body)
    outcome, detail = provision_outcome(payload)
    return {
        "servicePrincipal": target.label,
        "subject": subject["displayName"],
        "subjectId": subject["objectId"],
        "subjectType": subject["objectTypeName"],
        "outcome": outcome,
        "detail": detail,
    }


def provision_outcome(payload: dict[str, Any]) -> tuple[str, str]:
    """Classify a provisionOnDemand response as applied, already-in-sync or failed.

    The verdict is not the HTTP status and not a field: it is JSON encoded inside the
    `key` string of a stringKeyStringValuePair, as `{"result": ..., "details": {...}}`.

    Anything unrecognised counts as failed rather than applied. A result this code has
    never seen is not evidence that provisioning happened, and on-demand provisioning is
    usually run precisely because something is already wrong.
    """
    import orjson

    raw = payload.get("key")
    if not isinstance(raw, str):
        return "failed", "Graph returned no provisioning result"
    try:
        verdict = orjson.loads(raw)
    except orjson.JSONDecodeError:
        return "failed", f"unreadable provisioning result: {raw[:120]}"

    result = str(verdict.get("result") or "").strip()
    details = verdict.get("details") or {}
    code = str(details.get("errorCode") or "")
    message = str(details.get("errorMessage") or "")
    detail = " ".join(part for part in (code, message) if part) or result

    if result.casefold() == "success":
        return "applied", detail
    if result.casefold() == "skipped" and code.casefold() in BENIGN_SKIP_CODES:
        return "already-in-sync", detail
    return "failed", detail


def report(records: list[dict[str, Any]], failed: list[tuple[str, str]], *, quiet: bool) -> None:
    """Print per-subject outcomes on stderr, then the summary.

    Every record is reported before the caller raises, so one failure in a batch does not
    hide the rest.
    """
    for record in records:
        if record["outcome"] == "already-in-sync":
            click.secho(
                f"{record['subject']} already matches the target; nothing to provision.",
                err=True,
                fg="cyan",
            )
        elif record["outcome"] == "failed":
            click.secho(
                f"{record['subject']} was not provisioned: {record['detail']}",
                err=True,
                fg="red",
            )
        elif not quiet:
            click.secho(f"{record['subject']} provisioned.", err=True, fg="green")

    for value, reason in failed:
        click.secho(f"Could not resolve '{value}': {reason}", err=True, fg="yellow")

    # Noun order matters: `summarise` pluralises by appending to the whole string, so
    # "provisioned subject" gives "2 provisioned subjects" where "subject provisioned"
    # would give "2 subject provisioneds".
    applied = [record for record in records if record["outcome"] == "applied"]
    summarise(len(applied), "provisioned subject", quiet=quiet)
