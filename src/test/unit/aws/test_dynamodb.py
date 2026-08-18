"""Unit tests for the pure parts of `pctl.aws.dynamodb.client`.

No AWS calls happen here. The interesting behaviour is the convenience layer: plain
JSON keys are converted to DynamoDB's typed form while already-typed input is passed
through untouched, request kwargs contain only what was asked for, and botocore's
error codes are translated into the CLI's exit-code tiers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pctl.aws.dynamodb.client import (
    ScanRequest,
    serialize_key,
    serialize_values,
    wrap_client_error,
)
from pctl.errors import NotFoundError, UpstreamError

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# key and value serialisation
# ---------------------------------------------------------------------------
def test_a_plain_key_is_given_dynamodb_types() -> None:
    assert serialize_key({"pk": "tenant#42"}) == {"pk": {"S": "tenant#42"}}


def test_a_numeric_value_becomes_an_n() -> None:
    assert serialize_key({"n": 7}) == {"n": {"N": "7"}}


def test_a_boolean_value_becomes_a_bool() -> None:
    assert serialize_key({"flag": True}) == {"flag": {"BOOL": True}}


def test_an_already_typed_key_is_passed_through_unchanged() -> None:
    """Copy-pasting DynamoDB JSON from the console has to keep working."""
    typed = {"pk": {"S": "tenant#42"}, "sk": {"S": "profile"}}
    assert serialize_key(typed) == typed


def test_a_mixed_shape_is_treated_as_plain_json() -> None:
    """One untyped value means the whole mapping is plain, so it all gets serialised."""
    result = serialize_key({"pk": {"S": "a"}, "sk": "profile"})
    assert result["sk"] == {"S": "profile"}
    assert result["pk"] == {"M": {"S": {"S": "a"}}}


def test_a_multi_key_dict_value_is_not_mistaken_for_a_type_tag() -> None:
    result = serialize_key({"attr": {"S": "a", "extra": "b"}})
    assert set(result["attr"]) == {"M"}


def test_an_unknown_single_key_dict_is_not_a_type_tag() -> None:
    result = serialize_key({"attr": {"NOPE": "a"}})
    assert set(result["attr"]) == {"M"}


def test_serialize_values_passes_none_through() -> None:
    assert serialize_values(None) is None


def test_serialize_values_passes_an_empty_mapping_through() -> None:
    """No expression values must stay absent rather than becoming an empty dict."""
    assert serialize_values({}) is None


def test_serialize_values_types_expression_placeholders() -> None:
    assert serialize_values({":s": "ACTIVE"}) == {":s": {"S": "ACTIVE"}}


# ---------------------------------------------------------------------------
# request construction
# ---------------------------------------------------------------------------
def test_minimal_request_only_names_the_table() -> None:
    assert ScanRequest(table="t").base_kwargs() == {"TableName": "t"}


def test_optional_parts_appear_only_when_set() -> None:
    request = ScanRequest(
        table="t",
        index="gsi1",
        projection="pk,sk",
        filter_expression="#s = :s",
        key_condition="pk = :pk",
        expression_values={":s": {"S": "ACTIVE"}},
        expression_names={"#s": "status"},
        consistent=True,
    )
    assert request.base_kwargs() == {
        "TableName": "t",
        "IndexName": "gsi1",
        "ProjectionExpression": "pk,sk",
        "FilterExpression": "#s = :s",
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":s": {"S": "ACTIVE"}},
        "ExpressionAttributeNames": {"#s": "status"},
        "ConsistentRead": True,
    }


def test_consistent_read_is_omitted_rather_than_false() -> None:
    """Sending ConsistentRead=False is legal but noisy; omit it instead."""
    assert "ConsistentRead" not in ScanRequest(table="t", consistent=False).base_kwargs()


def test_paging_and_limits_are_not_request_kwargs() -> None:
    """`--limit`, `--page-size` and `--segments` are client-side concerns."""
    request = ScanRequest(table="t", limit=5, page_size=10, segments=4)
    assert request.base_kwargs() == {"TableName": "t"}


# ---------------------------------------------------------------------------
# error translation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ResourceNotFoundException", NotFoundError),
        ("AccessDeniedException", UpstreamError),
        ("UnrecognizedClientException", UpstreamError),
        ("ExpiredTokenException", UpstreamError),
        ("ValidationException", UpstreamError),
        ("ProvisionedThroughputExceededException", UpstreamError),
    ],
)
def test_error_codes_map_to_error_tiers(
    client_error: Callable[..., Exception], code: str, expected: type[Exception]
) -> None:
    assert isinstance(wrap_client_error(client_error(code), "my-table"), expected)


def test_a_missing_table_names_the_table_it_looked_for(
    client_error: Callable[..., Exception],
) -> None:
    error = wrap_client_error(client_error("ResourceNotFoundException"), "my-table")
    assert "my-table" in str(error)


def test_access_denied_keeps_the_service_message(
    client_error: Callable[..., Exception],
) -> None:
    error = wrap_client_error(
        client_error("AccessDeniedException", "not authorized to perform dynamodb:Scan"),
        "my-table",
    )
    assert "not authorized" in str(error)


def test_expired_credentials_say_so_plainly(client_error: Callable[..., Exception]) -> None:
    """This is the most common failure in practice, so the wording matters."""
    error = wrap_client_error(client_error("ExpiredTokenException"), "t")
    assert "expired" in str(error).lower()


def test_an_unknown_code_still_becomes_an_upstream_error(
    client_error: Callable[..., Exception],
) -> None:
    error = wrap_client_error(client_error("SomethingNew"), "t")
    assert isinstance(error, UpstreamError)
    assert "SomethingNew" in str(error)


def test_an_exception_without_a_response_is_handled() -> None:
    """Not every failure that reaches this helper is a ClientError."""
    error = wrap_client_error(RuntimeError("socket closed"), "t")
    assert isinstance(error, UpstreamError)


def test_validation_errors_are_upstream_not_usage(
    client_error: Callable[..., Exception],
) -> None:
    """DynamoDB rejected a well-formed request, so it is exit 5, not exit 2."""
    error: Any = wrap_client_error(client_error("ValidationException"), "t")
    assert error.exit_code == 5
