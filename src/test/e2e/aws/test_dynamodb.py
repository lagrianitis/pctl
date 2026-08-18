"""End-to-end: `pctl aws ddb`, against DynamoDB faked with moto.

The unit tier proves the transport builds correct request kwargs. Here the whole path
runs, so a command that builds a correct ScanRequest but loses attributes in the
renderer still fails.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from helpers import ITEM_COUNT, REGION, lines, ok

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
def test_tables_lists_the_table(ddb: Any, ddb_table: str) -> None:
    result = ok(ddb("-o", "ndjson", "tables"))

    assert json.loads(lines(result.stdout)[0])["table"] == ddb_table


def test_describe_returns_the_raw_describe_table_payload(ddb: Any, ddb_table: str) -> None:
    """`-o json` is an escape hatch: pass the API response through unreshaped."""
    payload = json.loads(ok(ddb("-o", "json", "describe", ddb_table)).stdout)

    assert payload["TableName"] == ddb_table
    assert "KeySchema" in payload


def test_describe_summarises_the_key_schema_for_humans(ddb: Any, ddb_table: str) -> None:
    result = ok(ddb("describe", ddb_table))

    assert "pk:HASH" in result.stdout
    assert "sk:RANGE" in result.stdout


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------
def test_a_parallel_scan_returns_every_item_exactly_once(ddb: Any, ddb_table: str) -> None:
    """Segments must partition the table, not overlap or drop rows."""
    result = ok(ddb("-o", "ndjson", "scan", ddb_table, "--segments", "4"))

    items = [json.loads(line) for line in lines(result.stdout)]
    assert len(items) == ITEM_COUNT
    assert len({item["pk"] for item in items}) == ITEM_COUNT


def test_dynamodb_types_deserialise_to_plain_json(ddb: Any, ddb_table: str) -> None:
    """A Decimal, a list and a map are the three that are easy to get wrong."""
    result = ok(ddb("-o", "ndjson", "scan", ddb_table, "-n", "1"))

    item = json.loads(lines(result.stdout)[0])
    assert item["budget"] == 1234.5
    assert item["count"] == 7
    assert item["tags"] == ["platform", "e2e"]
    assert item["meta"] == {"region": REGION}


def test_limit_stops_after_n_items(ddb: Any, ddb_table: str) -> None:
    result = ok(ddb("-o", "ndjson", "scan", ddb_table, "-n", "3"))

    assert len(lines(result.stdout)) == 3


def test_a_filter_expression_is_applied_server_side(ddb: Any, ddb_table: str) -> None:
    result = ok(
        ddb(
            "-o",
            "ndjson",
            "scan",
            ddb_table,
            "--filter",
            "#s = :s",
            "--names",
            '{"#s":"status"}',
            "--values",
            '{":s":"ACTIVE"}',
        )
    )

    rows = lines(result.stdout)
    assert {json.loads(line)["status"] for line in rows} == {"ACTIVE"}
    assert len(rows) == ITEM_COUNT // 2


def test_a_projection_limits_the_attributes_returned(ddb: Any, ddb_table: str) -> None:
    """Narrowing server-side is what keeps a large table cheap to read."""
    result = ok(
        ddb(
            "-o",
            "ndjson",
            "scan",
            ddb_table,
            "--projection",
            "pk,#s",
            "--names",
            '{"#s":"status"}',
            "-n",
            "1",
        )
    )

    assert set(json.loads(lines(result.stdout)[0])) == {"pk", "status"}


def test_an_empty_table_produces_no_rows(ddb: Any, empty_table: str) -> None:
    result = ok(ddb("-o", "ndjson", "scan", empty_table))

    assert lines(result.stdout) == []


# ---------------------------------------------------------------------------
# query and get
# ---------------------------------------------------------------------------
def test_query_by_partition_key_returns_the_match(ddb: Any, ddb_table: str) -> None:
    payload = json.loads(
        ok(
            ddb(
                "-o",
                "json",
                "query",
                ddb_table,
                "--key",
                "pk = :pk",
                "--values",
                '{":pk":"acct#007"}',
            )
        ).stdout
    )

    assert isinstance(payload, list)
    assert payload[0]["pk"] == "acct#007"


def test_query_supports_begins_with_on_the_sort_key(ddb: Any, ddb_table: str) -> None:
    ok(
        ddb(
            "-o",
            "json",
            "query",
            ddb_table,
            "--key",
            "pk = :pk AND begins_with(sk, :s)",
            "--values",
            '{":pk":"acct#007",":s":"pro"}',
        )
    )


def test_get_accepts_a_plain_json_key(ddb: Any, ddb_table: str) -> None:
    """Typing a key in DynamoDB's wire format by hand is the thing to avoid."""
    payload = json.loads(
        ok(ddb("-o", "json", "get", ddb_table, '{"pk":"acct#003","sk":"profile"}')).stdout
    )

    assert payload["pk"] == "acct#003"


def test_get_also_accepts_a_dynamodb_typed_key(ddb: Any, ddb_table: str) -> None:
    """Typed JSON passes through, so output from another tool can be piped back in."""
    payload = json.loads(
        ok(
            ddb(
                "-o",
                "json",
                "get",
                ddb_table,
                '{"pk":{"S":"acct#004"},"sk":{"S":"profile"}}',
            )
        ).stdout
    )

    assert payload["pk"] == "acct#004"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def test_csv_header_and_rows_honour_columns(ddb: Any, ddb_table: str) -> None:
    result = ok(ddb("-o", "csv", "scan", ddb_table, "-c", "pk,status,budget", "-n", "2"))

    rows = lines(result.stdout)
    assert rows[0] == "pk,status,budget"
    assert len(rows) == 3


def test_table_output_has_a_header_and_a_rule(ddb: Any, ddb_table: str) -> None:
    result = ok(ddb("scan", ddb_table, "-c", "pk,status", "-n", "2"))

    rows = lines(result.stdout)
    assert rows[0].split() == ["pk", "status"]
    assert set(rows[1]) <= {"-", " "}


# ---------------------------------------------------------------------------
# aliases and prefixes, end to end rather than help-only
# ---------------------------------------------------------------------------
def test_the_dynamodb_service_name_resolves(runner: Any, cli: Any, ddb_table: str) -> None:
    """`ddb` is the exposed name, but the package is `dynamodb` and both must work."""
    ok(runner.invoke(cli, ["-o", "ndjson", "aws", "dynamodb", "scan", ddb_table, "-n", "1"]))


def test_an_unambiguous_action_prefix_resolves(ddb: Any, ddb_table: str) -> None:
    ok(ddb("-o", "ndjson", "sc", ddb_table, "-n", "1"))
