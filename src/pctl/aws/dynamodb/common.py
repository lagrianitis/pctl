"""Options and parsing shared by the DynamoDB actions.

Kept out of `__init__.py` for the same reason as the groups service: a package
namespace also holds its submodules (`dynamodb.get`, `dynamodb.scan`), which would
shadow any same-named global used at runtime.
"""

from __future__ import annotations

from typing import Any

import click


def read_options(func: Any) -> Any:
    """Options shared by the read actions (scan and query)."""
    func = click.option(
        "--names",
        "expression_names",
        metavar="JSON",
        help='ExpressionAttributeNames, e.g. \'{"#s": "status"}\'.',
    )(func)
    func = click.option(
        "--values",
        "expression_values",
        metavar="JSON",
        help='Expression values as plain JSON, e.g. \'{":s": "ACTIVE"}\'.',
    )(func)
    func = click.option(
        "--projection",
        metavar="EXPR",
        help="ProjectionExpression: fetch only these attributes (less data, faster).",
    )(func)
    func = click.option("--index", metavar="NAME", help="Query or scan a secondary index.")(func)
    func = click.option("--filter", "filter_expression", metavar="EXPR", help="FilterExpression.")(
        func
    )
    func = click.option("--consistent", is_flag=True, help="Use a strongly consistent read.")(func)
    func = click.option("--page-size", type=click.IntRange(1, 1000), help="Items per page.")(func)
    func = click.option("-n", "--limit", type=click.IntRange(min=1), help="Stop after N items.")(
        func
    )
    return func


def parse_json_option(raw: str | None, hint: str) -> dict[str, Any] | None:
    """Parse a JSON object passed on the command line, with a friendly error."""
    if not raw:
        return None
    import orjson

    try:
        parsed = orjson.loads(raw)
    except orjson.JSONDecodeError as exc:
        raise click.BadParameter(f"invalid JSON: {exc}", param_hint=hint) from exc
    if not isinstance(parsed, dict):
        raise click.BadParameter("expected a JSON object", param_hint=hint)
    return parsed
