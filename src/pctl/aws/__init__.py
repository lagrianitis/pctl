"""The `aws` case: everything that talks to AWS.

This package holds the case-level group and anything shared across AWS services.
Services live in subpackages (`dynamodb`, exposed as `ddb`), each with one module
per action.
"""

from __future__ import annotations

import click

from ..config import AppContext
from ..lazy import PctlGroup

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

LAZY_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "ddb": ("pctl.aws.dynamodb:ddb", "Read items and metadata from DynamoDB tables."),
}

ALIASES = {"dynamodb": "ddb"}


@click.group(
    name="aws",
    cls=PctlGroup,
    lazy_subcommands=LAZY_SUBCOMMANDS,
    aliases=ALIASES,
    context_settings=CONTEXT_SETTINGS,
)
@click.pass_context
def aws(ctx: click.Context) -> None:
    """AWS: DynamoDB access.

    Credentials resolve through the standard SDK chain, so profiles, SSO, assumed
    roles and instance credentials behave as they do with the AWS CLI.
    """
    ctx.ensure_object(AppContext)


__all__ = ["CONTEXT_SETTINGS", "aws"]
