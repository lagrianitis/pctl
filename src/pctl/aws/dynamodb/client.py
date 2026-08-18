"""DynamoDB access.

The AWS SDK is synchronous, so throughput comes from parallel scan segments: the
table's key space is split into `TotalSegments` and worked by a thread pool, with
pages pushed onto a bounded queue that the caller drains lazily. That keeps memory
flat and lets the renderer start emitting rows while later segments are still in
flight.

botocore clients are documented as thread safe (sessions and resources are not), so
a single client is shared across workers with a connection pool sized to match.
"""

from __future__ import annotations

import contextlib
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from ...config import AwsConfig
from ...errors import ConfigError, NotFoundError, UpstreamError

_SENTINEL = object()
MAX_SEGMENTS = 64


@dataclass(slots=True)
class ScanRequest:
    """Everything needed to run a scan or query, kept separate from CLI parsing."""

    table: str
    index: str | None = None
    projection: str | None = None
    filter_expression: str | None = None
    key_condition: str | None = None
    expression_values: dict[str, Any] | None = None
    expression_names: dict[str, str] | None = None
    consistent: bool = False
    page_size: int | None = None
    limit: int | None = None
    segments: int = 1
    descending: bool = False

    def base_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"TableName": self.table}
        if self.index:
            kwargs["IndexName"] = self.index
        if self.projection:
            kwargs["ProjectionExpression"] = self.projection
        if self.filter_expression:
            kwargs["FilterExpression"] = self.filter_expression
        if self.key_condition:
            kwargs["KeyConditionExpression"] = self.key_condition
        if self.expression_values:
            kwargs["ExpressionAttributeValues"] = self.expression_values
        if self.expression_names:
            kwargs["ExpressionAttributeNames"] = self.expression_names
        if self.consistent:
            kwargs["ConsistentRead"] = True
        return kwargs


def make_client(config: AwsConfig, *, max_pool: int = 10) -> Any:
    """Create a DynamoDB client. boto3 is imported here to keep startup fast."""
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import BotoCoreError, NoRegionError

    boto_config = BotoConfig(
        max_pool_connections=max(10, max_pool),
        retries={"max_attempts": 8, "mode": "adaptive"},
        user_agent_extra="pctl",
        tcp_keepalive=True,
    )
    try:
        session = boto3.session.Session(
            profile_name=config.profile or None,
            region_name=config.region or None,
        )
        return session.client(
            "dynamodb", endpoint_url=config.endpoint_url or None, config=boto_config
        )
    except NoRegionError as exc:
        raise ConfigError("No AWS region configured. Pass --region, or set AWS_REGION.") from exc
    except BotoCoreError as exc:
        raise ConfigError(f"Could not create an AWS session: {exc}") from exc


def deserializer() -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a function converting DynamoDB-typed items into plain Python."""
    from boto3.dynamodb.types import TypeDeserializer

    deserialize = TypeDeserializer().deserialize

    def convert(item: dict[str, Any]) -> dict[str, Any]:
        return {key: deserialize(value) for key, value in item.items()}

    return convert


def serialize_key(key: dict[str, Any]) -> dict[str, Any]:
    """Accept plain JSON (`{"pk": "a"}`) or DynamoDB JSON (`{"pk": {"S": "a"}}`)."""
    if _looks_typed(key):
        return key
    from boto3.dynamodb.types import TypeSerializer

    serialize = TypeSerializer().serialize
    return {name: serialize(value) for name, value in key.items()}


def serialize_values(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if not values:
        return None
    return serialize_key(values)


_TYPE_TAGS = frozenset({"S", "N", "B", "SS", "NS", "BS", "M", "L", "NULL", "BOOL"})


def _looks_typed(payload: dict[str, Any]) -> bool:
    for value in payload.values():
        if not isinstance(value, dict) or len(value) != 1:
            return False
        if next(iter(value)) not in _TYPE_TAGS:
            return False
    return bool(payload)


def wrap_client_error(exc: Exception, table: str) -> Exception:
    """Turn a botocore ClientError into an pctl error with a useful message."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    message = getattr(exc, "response", {}).get("Error", {}).get("Message", str(exc))
    if code in {"ResourceNotFoundException"}:
        return NotFoundError(f"Table or index not found: {table}")
    if code in {"AccessDeniedException", "UnrecognizedClientException"}:
        return UpstreamError(f"Access denied for {table}: {message}")
    if code in {"ExpiredTokenException", "InvalidSignatureException"}:
        return UpstreamError(f"AWS credentials are expired or invalid: {message}")
    if code in {"ValidationException"}:
        return UpstreamError(f"DynamoDB rejected the request: {message}")
    return UpstreamError(f"DynamoDB error{f' ({code})' if code else ''}: {message}")


def list_tables(client: Any) -> Iterator[str]:
    for page in client.get_paginator("list_tables").paginate():
        yield from page.get("TableNames", [])


def describe_table(client: Any, table: str) -> dict[str, Any]:
    from botocore.exceptions import ClientError

    try:
        return client.describe_table(TableName=table)["Table"]
    except ClientError as exc:
        raise wrap_client_error(exc, table) from exc


def query(
    client: Any,
    request: ScanRequest,
    *,
    log: Callable[[str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream items from a Query, following LastEvaluatedKey."""
    from botocore.exceptions import ClientError

    convert = deserializer()
    kwargs = request.base_kwargs()
    if request.descending:
        kwargs["ScanIndexForward"] = False
    emitted = 0
    pages = 0
    try:
        for page in _paginate(client, "query", kwargs, request):
            pages += 1
            items = page.get("Items", ())
            if log:
                log(f"query page {pages}: {len(items)} items")
            for item in items:
                yield convert(item)
                emitted += 1
                if request.limit is not None and emitted >= request.limit:
                    return
    except ClientError as exc:
        raise wrap_client_error(exc, request.table) from exc


def get_item(client: Any, table: str, key: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
    from botocore.exceptions import ClientError

    try:
        response = client.get_item(TableName=table, Key=serialize_key(key), **kwargs)
    except ClientError as exc:
        raise wrap_client_error(exc, table) from exc
    item = response.get("Item")
    return deserializer()(item) if item else None


def scan(
    client: Any,
    request: ScanRequest,
    *,
    log: Callable[[str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream items from a scan, using parallel segments when `segments > 1`."""
    if request.segments <= 1:
        yield from _scan_sequential(client, request, log=log)
    else:
        yield from _scan_parallel(client, request, log=log)


def _paginate(
    client: Any, operation: str, kwargs: dict[str, Any], request: ScanRequest
) -> Iterator[dict[str, Any]]:
    pagination: dict[str, Any] = {}
    if request.page_size:
        pagination["PageSize"] = request.page_size
    if request.limit is not None and request.segments <= 1:
        # Let botocore stop early; MaxItems is per paginator, so only safe when
        # a single segment is doing all the work.
        pagination["MaxItems"] = request.limit
    paginator = client.get_paginator(operation)
    return paginator.paginate(**kwargs, PaginationConfig=pagination)


def _scan_sequential(
    client: Any, request: ScanRequest, *, log: Callable[[str], None] | None
) -> Iterator[dict[str, Any]]:
    from botocore.exceptions import ClientError

    convert = deserializer()
    emitted = 0
    pages = 0
    try:
        for page in _paginate(client, "scan", request.base_kwargs(), request):
            pages += 1
            items = page.get("Items", ())
            if log:
                log(f"scan page {pages}: {len(items)} items")
            for item in items:
                yield convert(item)
                emitted += 1
                if request.limit is not None and emitted >= request.limit:
                    return
    except ClientError as exc:
        raise wrap_client_error(exc, request.table) from exc


def _scan_parallel(
    client: Any, request: ScanRequest, *, log: Callable[[str], None] | None
) -> Iterator[dict[str, Any]]:
    segments = min(request.segments, MAX_SEGMENTS)
    convert = deserializer()
    pages: queue.Queue[Any] = queue.Queue(maxsize=segments * 2)
    stop = threading.Event()

    def worker(segment: int) -> None:
        from botocore.exceptions import ClientError

        kwargs = request.base_kwargs() | {"Segment": segment, "TotalSegments": segments}
        try:
            for page in _paginate(client, "scan", kwargs, request):
                if stop.is_set():
                    break
                pages.put(page.get("Items", ()))
        except ClientError as exc:
            pages.put(wrap_client_error(exc, request.table))
        except Exception as exc:  # surface anything else to the consumer thread
            pages.put(exc)
        finally:
            pages.put(_SENTINEL)

    threads = [
        threading.Thread(target=worker, args=(index,), name=f"pctl-scan-{index}", daemon=True)
        for index in range(segments)
    ]
    for thread in threads:
        thread.start()
    if log:
        log(f"parallel scan across {segments} segments")

    emitted = 0
    finished = 0
    try:
        while finished < segments:
            batch = pages.get()
            if batch is _SENTINEL:
                finished += 1
                continue
            if isinstance(batch, BaseException):
                raise batch
            for item in batch:
                yield convert(item)
                emitted += 1
                if request.limit is not None and emitted >= request.limit:
                    return
    finally:
        stop.set()
        # Drain the queue so workers blocked on put() can finish and exit promptly.
        while any(thread.is_alive() for thread in threads):
            with contextlib.suppress(queue.Empty):
                pages.get(timeout=0.05)
