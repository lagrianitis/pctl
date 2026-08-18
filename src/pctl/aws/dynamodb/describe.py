"""Action: `pctl aws ddb describe`."""

from __future__ import annotations

from typing import Any

import click

from ...config import AppContext, OutputFormat
from ...options import aws_options, output_options
from ...output import Renderer


@click.command(name="describe")
@click.argument("table")
@aws_options
@output_options
@click.pass_context
def command(ctx: click.Context, table: str) -> None:
    """Show a table's keys, indexes, item count and size.

    Table output is a summary; use -o json for the full DescribeTable payload.
    """
    from .client import describe_table, make_client

    app = ctx.ensure_object(AppContext)
    described = describe_table(make_client(app.aws()), table)

    record: dict[str, Any] = described
    if app.output is OutputFormat.TABLE:
        record = _summary(described)
    with Renderer(app.output, single=True) as renderer:
        renderer.write(record)


def _summary(described: dict[str, Any]) -> dict[str, Any]:
    indexes = (described.get("GlobalSecondaryIndexes") or []) + (
        described.get("LocalSecondaryIndexes") or []
    )
    return {
        "table": described.get("TableName"),
        "status": described.get("TableStatus"),
        "items": described.get("ItemCount"),
        "sizeBytes": described.get("TableSizeBytes"),
        "keys": [
            f"{element.get('AttributeName')}:{element.get('KeyType')}"
            for element in described.get("KeySchema", [])
        ],
        "indexes": [index.get("IndexName") for index in indexes],
    }
