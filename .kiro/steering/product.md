# Product

`pctl` is a fast command-line tool for the AWS Platform team that reads from, and for a
small set of Entra ID operations writes to, multiple cloud and SaaS providers behind one
consistent interface.

## What it covers today

- **Microsoft Graph** (`pctl azure`) — acquire and cache Entra ID tokens, and a `raw`
  escape hatch that calls any Graph path with auth, retries and pagination handled.
  Services, with portal-name aliases such as `enterprise-apps` and `access-packages`:
  - `groups` — list every group across paginated results, resolve by display name, and
    stream members or owners.
  - `users` — find a user by email, display name or object ID.
  - `apps` — list and get application registrations.
  - `sp` — list and get service principals (Enterprise Applications), read app role
    assignments and owners, add or remove an owner, and provision users or groups.
  - `eam` — entitlement management: list and get access packages and catalogs, list,
    add and remove assignments by email, delete a package, and check an assignment
    request.
- **AWS DynamoDB** (`pctl aws ddb`) — list and describe tables, and read items via
  scan (including parallel segments), query or get-item. Read-only.
- **Discovery** — `pctl commands` lists every command in one greppable table,
  `pctl tree` draws the hierarchy, and `pctl completion` prints the shell completion line.

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
- **Writes are explicit and refuse to guess.** The few commands that change the tenant
  (`add-owner`, `remove-owner`, `provision`, `add-assignment`, `remove-assignment`,
  `delete-package`) are their own named actions, never a flag on a read, and an
  ambiguous name is rejected with exit 2 rather than resolved to the first match.

## Audience

Platform engineers and CI jobs. Ergonomics matter (aliases, unambiguous command
prefixes, `-o` formats), but never at the cost of clean machine-readable output.
