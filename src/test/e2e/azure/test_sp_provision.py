"""End-to-end: `pctl azure sp provision`, on-demand provisioning.

Its own module rather than part of `test_sp_owners.py` because the interesting property is
different. The owner writes are about idempotency; this one is about *not trusting the
HTTP status*: Graph answers 200 and buries the real verdict in a JSON string, so a command
that only checked the status code would report success for a subject it failed to
provision. Most of what follows pins that down.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from helpers import GRAPH, failed, lines, ok

pytestmark = pytest.mark.e2e

SP_ID = "sp-0001"
SCIM_APP = "Company Incident.io SCIM"
JOB_ID = "3f7565a3-fde6-4e4d-bda8-1bb70aba3612"
# Versioned rule IDs are not plain GUIDs, and this one is deliberately suffixed so a
# regression that validates it as an object ID fails here.
RULE_ID = "33f7c90d-bf71-41b1-bda6-aaf0ddbee5d8#V2"
GROUP_ID = "9bb0f679-a883-4a6f-8260-35b491b8b8c8"
ANN_ID = "e6901838-637f-4bc7-b843-a8a7725a4872"

SYNC = f"{GRAPH}/servicePrincipals/{SP_ID}/synchronization"


def verdict(result: str, **details: str) -> dict[str, str]:
    """A stringKeyStringValuePair the way Graph really sends it.

    Both members are JSON *strings*, not objects. Building the fixture this way rather
    than as nested JSON is the point: a test using the convenient shape would pass while
    the real response broke the command.
    """
    return {
        "key": json.dumps({"result": result, "details": details}),
        "value": json.dumps({}),
    }


@pytest.fixture
def provisioning(graph: Any) -> Any:
    """An application with one sync job, one rule, and a group and user to provision."""
    import httpx

    graph.get(f"{GRAPH}/servicePrincipals").mock(
        return_value=httpx.Response(
            200,
            json={"value": [{"id": SP_ID, "displayName": SCIM_APP, "appId": "app-1"}]},
        )
    )
    graph.get(f"{SYNC}/jobs", name="jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": JOB_ID,
                        "templateId": "scim",
                        "schedule": {"state": "Active"},
                    }
                ]
            },
        )
    )
    graph.get(f"{SYNC}/jobs/{JOB_ID}/schema", name="schema").mock(
        return_value=httpx.Response(
            200,
            json={
                "synchronizationRules": [
                    {
                        "id": RULE_ID,
                        "name": "USER_OUTBOUND",
                        "sourceDirectoryName": "Azure Active Directory",
                        "targetDirectoryName": "customappsso",
                    }
                ]
            },
        )
    )
    graph.get(f"{GRAPH}/groups", name="groups").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "value": (
                    [{"id": GROUP_ID, "displayName": "AWS Platform Admins"}]
                    if "AWS Platform Admins" in str(request.url)
                    else []
                )
            },
        )
    )
    graph.get(f"{GRAPH}/users", name="users").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "value": (
                    [
                        {
                            "id": ANN_ID,
                            "displayName": "Ann Example",
                            "userPrincipalName": "ann@example.com",
                            "mail": "ann@example.com",
                        }
                    ]
                    if "ann@example.com" in str(request.url)
                    else []
                )
            },
        )
    )
    return graph


@pytest.fixture
def succeeds(provisioning: Any) -> Any:
    """provisionOnDemand answering Success, named so a test can inspect the request.

    Every route in these fixtures is named, because respx matches routes in the order they
    were added: re-registering the same pattern inside a test would be shadowed by the
    original and quietly test nothing. Overrides therefore assign to
    `fixture["<name>"].return_value` or `.side_effect`, which respx rolls back per test.
    """
    import httpx

    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand", name="provision").mock(
        return_value=httpx.Response(200, json=verdict("Success"))
    )
    return provisioning


# ---------------------------------------------------------------------------
# the request body
# ---------------------------------------------------------------------------
def test_the_body_matches_the_documented_shape(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """parameters -> subjects -> objectId/objectTypeName, with the ruleId alongside."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
            ],
        )
    )

    body = json.loads(succeeds["provision"].calls[0].request.content)
    assert body == {
        "parameters": [
            {
                "ruleId": RULE_ID,
                "subjects": [{"objectId": GROUP_ID, "objectTypeName": "Group"}],
            }
        ]
    }


def test_a_user_subject_is_typed_user(runner: Any, cli: Any, succeeds: Any) -> None:
    """Capitalised, which is what Entra ID to application provisioning expects."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        )
    )

    body = json.loads(succeeds["provision"].calls[0].request.content)
    subject = body["parameters"][0]["subjects"][0]
    assert subject == {"objectId": ANN_ID, "objectTypeName": "User"}


def test_a_versioned_rule_id_is_passed_through_unchanged(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """`<guid>#V2` is a legal rule ID, so it must not be validated as a GUID."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
            ],
        )
    )

    body = json.loads(succeeds["provision"].calls[0].request.content)
    assert body["parameters"][0]["ruleId"] == RULE_ID


def test_each_subject_gets_its_own_request(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """One verdict comes back per response, so batching would lose the attribution."""
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
                "--user",
                "ann@example.com",
            ],
        )
    )

    assert succeeds["provision"].call_count == 2
    assert len(lines(result.stdout)) == 2


def test_a_duplicate_subject_is_provisioned_once(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
                "--group",
                "AWS Platform Admins",
            ],
        )
    )

    assert succeeds["provision"].call_count == 1
    assert len(lines(result.stdout)) == 1


# ---------------------------------------------------------------------------
# the verdict hidden in the response
# ---------------------------------------------------------------------------
def test_success_reports_applied_and_exits_0(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
            ],
        )
    )

    assert json.loads(lines(result.stdout)[0])["outcome"] == "applied"


def test_a_redundant_export_is_already_in_sync_and_exits_0(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """Source and target already match, which is the on-demand equivalent of a no-op."""
    import httpx

    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand").mock(
        return_value=httpx.Response(
            200,
            json=verdict(
                "Skipped",
                errorCode="RedundantExport",
                errorMessage="The state of the user in both systems already match.",
            ),
        )
    )

    result = ok(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
            ],
        )
    )

    assert json.loads(lines(result.stdout)[0])["outcome"] == "already-in-sync"


def test_an_out_of_scope_skip_is_a_failure(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """Also a Skipped, but nothing was provisioned, so exit 0 would be a lie."""
    import httpx

    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand").mock(
        return_value=httpx.Response(
            200,
            json=verdict(
                "Skipped",
                errorCode="NotEffectivelyEntitled",
                errorMessage="The user is not assigned to the application.",
            ),
        )
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        5,
    )

    assert "not assigned to the application" in result.stderr


def test_a_failure_verdict_exits_5_despite_the_200(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """The whole reason this command does not trust the status code."""
    import httpx

    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand").mock(
        return_value=httpx.Response(
            200,
            json=verdict(
                "Failure", errorCode="SchemaError", errorMessage="Bad mapping."
            ),
        )
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        5,
    )

    assert "SchemaError" in result.stderr


def test_an_unrecognised_verdict_is_not_treated_as_success(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """A result this code has never seen is not evidence that provisioning happened."""
    import httpx

    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand").mock(
        return_value=httpx.Response(200, json=verdict("SomethingNew"))
    )

    failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        5,
    )


def test_an_unreadable_verdict_exits_5(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """`key` is a JSON string by contract; if it stops being one, say so rather than crash."""
    import httpx

    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand").mock(
        return_value=httpx.Response(200, json={"key": "not json at all", "value": "{}"})
    )

    failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        5,
    )


def test_one_failed_subject_still_reports_the_others(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """Raising on the first failure would hide the rest of the batch."""
    import httpx

    responses = [
        httpx.Response(200, json=verdict("Success")),
        httpx.Response(200, json=verdict("Failure", errorCode="SchemaError")),
    ]
    provisioning.post(f"{SYNC}/jobs/{JOB_ID}/provisionOnDemand").mock(
        side_effect=responses
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "-o",
                "ndjson",
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
                "--user",
                "ann@example.com",
            ],
        ),
        5,
    )

    outcomes = [json.loads(line)["outcome"] for line in lines(result.stdout)]
    assert sorted(outcomes) == ["applied", "failed"]


# ---------------------------------------------------------------------------
# job and rule resolution
# ---------------------------------------------------------------------------
def test_a_single_job_and_rule_need_no_flags(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """The common case: one SCIM job, one rule, nothing to disambiguate."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        )
    )

    assert succeeds["provision"].call_count == 1


def test_an_application_without_provisioning_exits_2(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """Provisioning was never configured, which is a config problem, not an upstream one."""
    import httpx

    provisioning["jobs"].return_value = httpx.Response(200, json={"value": []})

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        2,
    )

    assert "provisioning is not enabled" in result.output


def test_a_missing_synchronization_segment_reads_as_not_enabled(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """An app with no provisioning may have no `synchronization` segment, so Graph 404s.

    Same meaning as an empty collection, and it must not surface as a raw upstream error.
    """
    import httpx

    provisioning["jobs"].return_value = httpx.Response(
        404, json={"error": {"code": "ResourceNotFound", "message": "No sync here."}}
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        2,
    )

    assert "provisioning is not enabled" in result.output


def test_a_forbidden_job_lookup_is_not_reported_as_not_enabled(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """A 403 is a missing permission. Calling it "not enabled" sends you to fix the wrong thing."""
    import httpx

    provisioning["jobs"].return_value = httpx.Response(
        403,
        json={
            "error": {
                "code": "Authorization_RequestDenied",
                "message": "Insufficient privileges to complete the operation.",
            }
        },
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        5,
    )

    assert "provisioning is not enabled" not in result.output
    assert "Insufficient privileges" in result.output


def test_several_jobs_are_refused_and_listed(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """Guessing could provision in the wrong direction."""
    import httpx

    provisioning["jobs"].return_value = httpx.Response(
        200,
        json={
            "value": [
                {"id": JOB_ID, "templateId": "scim"},
                {"id": "second-job", "templateId": "AD2AAD"},
            ]
        },
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        2,
    )

    assert "--job" in result.output
    assert "second-job" in result.output


def test_explicit_job_and_rule_skip_both_lookups(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """Naming both saves two round trips, one of which fetches the whole sync schema."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
                "--job",
                JOB_ID,
                "--rule",
                RULE_ID,
            ],
        )
    )

    assert succeeds["jobs"].call_count == 0
    assert succeeds["schema"].call_count == 0
    assert succeeds["provision"].call_count == 1


def test_several_rules_are_refused_and_listed(
    runner: Any, cli: Any, provisioning: Any
) -> None:
    """Provisioning through the wrong rule writes the wrong attributes."""
    import httpx

    provisioning["schema"].return_value = httpx.Response(
        200,
        json={
            "synchronizationRules": [
                {
                    "id": RULE_ID,
                    "sourceDirectoryName": "Azure Active Directory",
                    "targetDirectoryName": "customappsso",
                },
                {
                    "id": "group-rule",
                    "sourceDirectoryName": "Azure Active Directory",
                    "targetDirectoryName": "groups",
                },
            ]
        },
    )

    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--user",
                "ann@example.com",
            ],
        ),
        2,
    )

    assert "--rule" in result.output
    assert "group-rule" in result.output


# ---------------------------------------------------------------------------
# subject resolution
# ---------------------------------------------------------------------------
def test_an_unknown_group_exits_4_and_names_it(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    result = failed(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "No Such Group",
            ],
        ),
        4,
    )

    assert "No Such Group" in result.stderr


def test_ignore_missing_tolerates_an_unresolvable_subject(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """The resolvable subject is still provisioned."""
    ok(
        runner.invoke(
            cli,
            [
                "azure",
                "sp",
                "provision",
                "--app",
                "incident",
                "--group",
                "AWS Platform Admins",
                "--group",
                "No Such Group",
                "--ignore-missing",
            ],
        )
    )

    assert succeeds["provision"].call_count == 1


def test_a_group_object_id_needs_no_lookup(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """A GUID is unambiguous, so it goes straight into the body."""
    ok(
        runner.invoke(
            cli, ["azure", "sp", "provision", "--app", "incident", "--group", GROUP_ID]
        )
    )

    body = json.loads(succeeds["provision"].calls[0].request.content)
    assert body["parameters"][0]["subjects"][0]["objectId"] == GROUP_ID


def test_an_ambiguous_group_name_is_refused(
    runner: Any, cli: Any, succeeds: Any
) -> None:
    """Stricter than `groups get`, which warns: this provisions into another system.

    Exit 4, not 2: an ambiguous name is collected as an unresolved subject alongside any
    other resolution failure, the same way the eam assignment writes treat it.
    """
    import httpx

    # side_effect, not return_value: the fixture set a side_effect on this route and respx
    # gives side_effect precedence, so a return_value here would never be used.
    succeeds["groups"].side_effect = lambda request: httpx.Response(
        200,
        json={
            "value": [
                {"id": "g1", "displayName": "Platform"},
                {"id": "g2", "displayName": "Platform"},
            ]
        },
    )

    result = failed(
        runner.invoke(
            cli,
            ["azure", "sp", "provision", "--app", "incident", "--group", "Platform"],
        ),
        4,
    )

    assert "2 groups match" in result.stderr
    assert succeeds["provision"].call_count == 0
