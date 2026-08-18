# Product

`pctl` is a fast command-line tool for the AWS Platform team that reads from
multiple cloud and SaaS providers behind one consistent interface.

## What it covers today

- **Microsoft Graph** (`pctl azure`) — acquire and cache Entra ID tokens, list every
  group in the tenant across paginated results, resolve groups by display name, and
  stream members or owners. A `raw` escape hatch calls any Graph path with auth,
  retries and pagination handled.
- **AWS DynamoDB** (`pctl aws ddb`) — list and describe tables, and read items via
  scan (including parallel segments), query or get-item.

## Design intent

- **Command shape is `case → service → action`** (`pctl aws ddb scan`). Adding a
  provider means adding a case package, not reshaping what already works.
- **Speed is a feature.** Lazy imports keep `pctl --help` in the low tens of
  milliseconds, tokens are cached on disk, Graph pages are prefetched, and payloads
  are narrowed server-side with `$select`/`$top`/`--projection`.
- **Pipe-friendly by default.** Data goes to stdout, diagnostics and summaries go to
  stderr. `ndjson` and `csv` stream, so memory stays flat on large result sets.
- **Scriptable exit codes.** 0 success, 1 generic, 2 usage/config, 3 auth,
  4 not found, 5 upstream, 130 interrupted, 141 broken pipe.
- **Secrets stay out of argv.** Client secrets are read from the environment or AWS
  Secrets Manager, never from a CLI flag.

## Audience

Platform engineers and CI jobs. Ergonomics matter (aliases, unambiguous command
prefixes, `-o` formats), but never at the cost of clean machine-readable output.
