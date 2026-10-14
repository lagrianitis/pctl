"""Showing a bearer token without leaking it, and reading what is inside one.

Every command that prints a token needs the same two things: a masked form for the
terminal, since scrollback and CI logs are not secret stores, and a way to look at the
claims when something is wrong. They started life inside `azure token` and moved here
when `oauth` became the second caller, so the two cannot drift apart.

The signature is never verified. This is for looking at a token, not for deciding
anything from it.
"""

from __future__ import annotations

from typing import Any

# Anything shorter has too little left to show once the ends are kept, so it is hidden.
MASK_MIN_LENGTH = 20
MASK_HEAD = 8
MASK_TAIL = 6


def mask(token: str) -> str:
    """The ends of a token and its length, which is enough to tell two tokens apart."""
    if len(token) <= MASK_MIN_LENGTH:
        return "…"
    return f"{token[:MASK_HEAD]}…{token[-MASK_TAIL:]} ({len(token)} chars)"


def decode_claims(token: str) -> dict[str, Any]:
    """Decode the JWT payload for inspection. The signature is NOT verified."""
    import base64

    import orjson

    parts = token.split(".")
    if len(parts) < 2:
        return {"error": "not a JWT"}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = orjson.loads(base64.urlsafe_b64decode(payload))
    except ValueError, orjson.JSONDecodeError:
        return {"error": "could not decode payload"}
    return claims if isinstance(claims, dict) else {"value": claims}
