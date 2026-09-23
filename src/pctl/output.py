"""Output rendering.

Records are written straight to `sys.stdout.buffer` as bytes produced by orjson,
which skips a text-encode pass per record. The `Renderer` API is incremental
(`write` per record, then `close`), so both the sync DynamoDB path and the async
Graph path stream through the same code without buffering the whole result set.

`ndjson` and `csv` are true streams: piping a large scan into another process
starts producing output immediately and keeps memory flat. `table` must buffer,
because column widths are only known once every row has been seen.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from decimal import Decimal
from types import TracebackType
from typing import Any

import orjson

from .config import OutputFormat

_JSON_OPTS = orjson.OPT_NON_STR_KEYS
_TABLE_MAX_WIDTH = 60
_FLUSH_EVERY = 512
_NULL = "-"


def _fallback(value: Any) -> Any:
    if isinstance(value, Decimal):
        # Keep integral values integral so a numeric `id` does not become 1.0.
        as_int = int(value)
        return as_int if value == as_int else float(value)
    if isinstance(value, set | frozenset):
        return sorted(value, key=str)
    if isinstance(value, bytes | bytearray):
        return value.hex()
    return str(value)


def dumps(value: Any, *, indent: bool = False) -> bytes:
    opts = _JSON_OPTS | (orjson.OPT_INDENT_2 if indent else 0)
    return orjson.dumps(value, default=_fallback, option=opts)


def _cell(value: Any) -> str:
    if value is None:
        return _NULL
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value or _NULL
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple):
        return ", ".join(_cell(v) for v in value) if value else _NULL
    if isinstance(value, dict):
        return dumps(value).decode()
    return str(_fallback(value))


def _truncate(text: str, limit: int) -> str:
    text = text.replace("\n", " ").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple | dict):
        return dumps(value).decode()
    return value if isinstance(value, str) else str(_fallback(value))


class Renderer:
    """Incremental writer. Use as a context manager, or `write()` then `close()`."""

    def __init__(
        self,
        fmt: OutputFormat | str,
        *,
        columns: Sequence[str] | None = None,
        single: bool = False,
    ) -> None:
        self.fmt = OutputFormat(fmt)
        self.columns = list(columns) if columns else None
        self.single = single
        self.count = 0
        self._broken = False
        self._pretty = self.fmt is OutputFormat.JSON and sys.stdout.isatty()
        self._pending: dict[str, Any] | None = None
        self._rows: list[dict[str, Any]] = []
        self._csv: Any = None
        self._csv_buffer: Any = None

    # -- plumbing ---------------------------------------------------------
    def _emit(self, chunk: bytes) -> None:
        if self._broken:
            return
        try:
            sys.stdout.buffer.write(chunk)
        except BrokenPipeError:
            self._broken = True

    def _flush(self) -> None:
        if self._broken:
            return
        try:
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            self._broken = True

    def __enter__(self) -> Renderer:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()

    # -- public API -------------------------------------------------------
    def write(self, record: dict[str, Any]) -> None:
        if self._broken:
            return
        match self.fmt:
            case OutputFormat.NDJSON:
                self._emit(dumps(record) + b"\n")
            case OutputFormat.JSON:
                self._write_json(record)
            case OutputFormat.CSV:
                self._write_csv(record)
            case OutputFormat.TABLE:
                self._rows.append(record)
        self.count += 1
        if self.count % _FLUSH_EVERY == 0:
            self._flush()

    def write_all(self, records: Iterable[dict[str, Any]]) -> int:
        for record in records:
            self.write(record)
        return self.count

    def close(self) -> int:
        match self.fmt:
            case OutputFormat.JSON:
                self._close_json()
            case OutputFormat.CSV:
                self._close_csv()
            case OutputFormat.TABLE:
                self._close_table()
        self._flush()
        return self.count

    # -- json -------------------------------------------------------------
    def _write_json(self, record: dict[str, Any]) -> None:
        if self.count == 0:
            # Hold the first record back: with `single` a lone result is emitted
            # as an object rather than a one-element array.
            self._pending = record
            return
        if self.count == 1:
            self._emit(b"[\n" if self._pretty else b"[")
            self._emit(self._json_item(self._pending))
            self._pending = None
        self._emit(b",\n" if self._pretty else b",")
        self._emit(self._json_item(record))

    def _json_item(self, record: dict[str, Any] | None) -> bytes:
        chunk = dumps(record, indent=self._pretty)
        return b"  " + chunk.replace(b"\n", b"\n  ") if self._pretty else chunk

    def _close_json(self) -> None:
        if self.count == 0:
            self._emit(b"null\n" if self.single else b"[]\n")
        elif self.count == 1:
            if self.single:
                self._emit(dumps(self._pending, indent=self._pretty) + b"\n")
            else:
                self._emit(b"[\n" if self._pretty else b"[")
                self._emit(self._json_item(self._pending))
                self._emit(b"\n]\n" if self._pretty else b"]\n")
        else:
            self._emit(b"\n]\n" if self._pretty else b"]\n")

    # -- csv --------------------------------------------------------------
    def _write_csv(self, record: dict[str, Any]) -> None:
        if self._csv is None:
            import csv
            import io

            header = self.columns or [k for k in record if not k.startswith("@odata.")]
            self.columns = header
            self._csv_buffer = io.StringIO(newline="")
            self._csv = csv.DictWriter(
                self._csv_buffer, fieldnames=header, extrasaction="ignore", restval=""
            )
            self._csv.writeheader()
        self._csv.writerow({key: _scalar(record.get(key)) for key in self.columns or ()})
        if self._csv_buffer.tell() > 32_768:
            self._drain_csv()

    def _drain_csv(self) -> None:
        self._emit(self._csv_buffer.getvalue().encode())
        self._csv_buffer.seek(0)
        self._csv_buffer.truncate(0)

    def _close_csv(self) -> None:
        if self._csv_buffer is not None:
            self._drain_csv()

    # -- table ------------------------------------------------------------
    def _close_table(self) -> None:
        if not self._rows:
            self._emit(b"No results.\n")
            return
        header = self.columns or _infer_columns(self._rows)
        cells = [
            [_truncate(_cell(row.get(col)), _TABLE_MAX_WIDTH) for col in header]
            for row in self._rows
        ]
        # Headers are printed verbatim: what you pass to --columns is what you see,
        # and table output stays consistent with csv.
        widths = [len(col) for col in header]
        for row_cells in cells:
            for index, text in enumerate(row_cells):
                widths[index] = max(widths[index], len(text))

        lines = [
            "  ".join(col.ljust(widths[i]) for i, col in enumerate(header)).rstrip(),
            "  ".join("-" * width for width in widths),
        ]
        lines.extend(
            "  ".join(text.ljust(widths[i]) for i, text in enumerate(row_cells)).rstrip()
            for row_cells in cells
        )
        self._emit(("\n".join(lines) + "\n").encode())


def _infer_columns(rows: Sequence[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            if not key.startswith("@odata."):
                seen.setdefault(key, None)
    return list(seen) or ["value"]


def render(
    records: Iterable[dict[str, Any]],
    fmt: OutputFormat | str,
    *,
    columns: Sequence[str] | None = None,
    single: bool = False,
) -> int:
    """Render a synchronous iterable and return the number of records written."""
    renderer = Renderer(fmt, columns=columns, single=single)
    renderer.write_all(records)
    return renderer.close()


def summarise(count: int, noun: str, *, quiet: bool = False) -> None:
    """Print a one-line count to stderr, keeping stdout machine-readable."""
    if quiet:
        return
    import click

    click.secho(f"{count} {noun}{'' if count == 1 else 's'}", err=True, dim=True)
