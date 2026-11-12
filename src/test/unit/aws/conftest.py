"""Fixtures shared by the AWS unit tests.

Everything AWS-specific that more than one test needs lives here, so the tests stay
about behaviour rather than setup.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest


class FakeClientError(Exception):
    """Shaped like botocore's ClientError, without importing botocore.

    `wrap_client_error` only reads `.response`, so a stand-in keeps these tests free
    of the SDK and fast to run.
    """

    def __init__(self, code: str, message: str = "boom") -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


@pytest.fixture
def client_error() -> Callable[..., FakeClientError]:
    """Build a botocore-shaped error for a given error code."""

    def make(code: str, message: str = "boom") -> FakeClientError:
        return FakeClientError(code, message)

    return make
