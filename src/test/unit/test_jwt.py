"""Unit tests for `pctl.jwt`: masking a token and reading its claims."""

from __future__ import annotations

import pytest

from helpers import FAKE_JWT
from pctl.jwt import decode_claims, mask

pytestmark = pytest.mark.unit

LONG_TOKEN = "header." + "A" * 40 + ".signature"


def test_a_long_token_keeps_only_its_ends_and_its_length() -> None:
    masked = mask(LONG_TOKEN)

    assert masked.startswith(LONG_TOKEN[:8])
    assert masked.endswith(f"({len(LONG_TOKEN)} chars)")
    assert LONG_TOKEN not in masked


def test_the_middle_of_a_token_never_appears() -> None:
    assert "A" * 10 not in mask(LONG_TOKEN)


def test_a_short_token_is_hidden_entirely() -> None:
    """Too little would be left once the ends were kept, so show nothing."""
    assert mask("short") == "…"


def test_claims_are_read_from_the_payload() -> None:
    assert decode_claims(FAKE_JWT) == {"app": "pctl"}


def test_a_value_with_no_dots_is_not_a_jwt() -> None:
    assert decode_claims("opaque-token") == {"error": "not a JWT"}


def test_an_undecodable_payload_is_reported_not_raised() -> None:
    assert decode_claims("header.!!!.signature") == {"error": "could not decode payload"}


def test_a_payload_that_is_not_an_object_is_wrapped() -> None:
    # "WzEsIDJd" is base64url for [1, 2]
    assert decode_claims("header.WzEsIDJd.signature") == {"value": [1, 2]}
