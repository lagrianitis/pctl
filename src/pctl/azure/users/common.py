"""Code shared by the `users` actions.

The lookup itself lives in `azure/common.py`, because `sp` needs the same resolution
when turning an owner argument into a directory object. What is left here is
presentation: which columns a terminal sees by default.
"""

from __future__ import annotations

from typing import Any

import click

from ..common import MATCH_MODES

DEFAULT_LIST_COLUMNS = ["displayName", "userPrincipalName", "mail", "id"]


def match_option(func: Any) -> Any:
    """`--match`, used when the argument is a display name rather than an address.

    Defaults to exact. An address or an object ID ignores this entirely, and those are
    the forms that identify one person unambiguously.
    """
    return click.option(
        "--match",
        "match_mode",
        type=click.Choice(MATCH_MODES),
        default="exact",
        show_default=True,
        help="How to match a display name: exact, prefix or search (substring).",
    )(func)
