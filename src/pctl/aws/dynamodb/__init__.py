"""The `dynamodb` service (exposed as `ddb`) under the `aws` case.

`__init__.py` declares the service group and its actions. Shared options and
parsing live in `common.py`, and the transport layer in `client.py`. One module per
action: `tables`, `describe`, `scan`, `query`, `get`.
"""

from __future__ import annotations

import click

from ...lazy import PctlGroup
from .common import parse_json_option, read_options

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "tables": ("pctl.aws.dynamodb.tables:command", "List tables in this account and region."),
    "describe": ("pctl.aws.dynamodb.describe:command", "Show keys, indexes, item count, size."),
    "scan": ("pctl.aws.dynamodb.scan:command", "Scan a table, streaming items as they arrive."),
    "query": ("pctl.aws.dynamodb.query:command", "Query a table or index by key condition."),
    "get": ("pctl.aws.dynamodb.get:command", "Fetch a single item by primary key."),
}


@click.group(name="ddb", cls=PctlGroup, lazy_subcommands=LAZY_SUBCOMMANDS)
def ddb() -> None:
    """Read items and metadata from DynamoDB tables."""


__all__ = ["ddb", "parse_json_option", "read_options"]
