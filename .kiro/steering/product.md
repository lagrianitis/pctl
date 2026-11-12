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
  - `apps` — list and get application registrations, list their client secrets and
    certificates with the days left and a status (optionally failing when one is close),
    create a client secret and store its value in AWS Secrets Manager, and remove one.
  - `sp` — list and get service principals (Enterprise Applications), read app role
    assignments and owners, add or remove an owner, and provision users or groups.
  - `eam` — entitlement management: list and get access packages and catalogs, list,
    add and remove assignments by email, delete a package, and check an assignment
    request.
- **AWS DynamoDB** (`pctl aws ddb`) — list and describe tables, and read items via
  scan (including parallel segments), query or get-item. Read-only.
- **OAuth 2.0** (`pctl oauth`, aliases `auth` and `auth0`) — a JWT from Auth0, or from any
  provider whose URLs you name. `token` is the client credentials grant for
  machines and is cached; `login` is the authorization code flow with PKCE through the
  browser for people and is never cached. Every setting is a flag and an environment
  variable, and the flag wins.
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
  4 not found, 5 upstream, 6 a requested check said no, 130 interrupted, 141 broken pipe.
- **Secrets stay out of argv.** Client secrets are read from the environment or AWS
  Secrets Manager, not from a CLI flag. The one exception is `pctl oauth --client-secret`,
  a deliberate choice recorded in `security.md`. `apps add-client-secret` is the one place
  `pctl` writes to Secrets Manager, to keep the value of a secret it just created.
- **Writes are explicit and refuse to guess.** The few commands that change the tenant
  (`add-owner`, `remove-owner`, `provision`, `add-assignment`, `remove-assignment`,
  `delete-package`, `add-client-secret`, `remove-client-secret`) are their own named
  actions, never a flag on a read, and an ambiguous name is rejected with exit 2 rather
  than resolved to the first match. A destructive one asks for more than a name:
  `remove-client-secret` takes a key ID only, and needs `--force` for a secret with more
  than 30 days left.

## Audience

Platform engineers and CI jobs. Ergonomics matter (aliases, unambiguous command
prefixes, `-o` formats), but never at the cost of clean machine-readable output.
