# pctl

One fast command line for the platform's providers. Today that means **Microsoft Graph**
(`pctl azure`), **AWS DynamoDB** (`pctl aws`) and **OAuth 2.0 tokens** (`pctl oauth`),
behind a single consistent interface.

> **This wiki is generated from the repository.** The source of truth is
> [`docs/wiki/`](https://github.com/lagrianitis/pctl/tree/main/docs/wiki), reviewed in the
> same pull requests as the code. Edit it there, not here, or your change will be
> overwritten on the next publish.

## The shape of every command

```
pctl [global options] <case> <service> <action> [options]
                       │       │         │
                       │       │         └── list, get, add-owner, scan …
                       │       └──────────── groups, users, apps, eam, sp, ddb
                       └──────────────────── azure, aws, oauth
```

`oauth` is the exception to the three levels: it has two actions and no service, like
`azure token`.

Two rules follow from it, and knowing them saves most of the guessing:

**Every value goes behind a named flag.** There are no positional arguments anywhere.
`--app`, `--access-package`, `--table`, `--group`, `--name`, `--target`. Argument order can
never change what a command acts on.

**Data goes to stdout, everything else to stderr.** Summaries, warnings and progress are
diagnostics, so `pctl ... -o ndjson | jq` is always clean.

## Start here

| Page                                           | What it covers                                     |
| ---------------------------------------------- | -------------------------------------------------- |
| [Getting Started](Getting-Started)             | Install, credentials, first commands               |
| [Finding a command](Finding-Commands)          | `pctl commands`, `pctl tree`, completion, aliases  |
| [Permissions](Permissions)                     | Every Graph permission and IAM action, per command |
| [Common options](Common-Options)               | The flags shared by many commands                  |
| [Output and exit codes](Output-and-Exit-Codes) | Four formats, and what each exit code means        |
| [Troubleshooting](Troubleshooting)             | Real failures and what they actually mean          |

## Command reference

**Microsoft Graph** — `pctl azure`

| Page                                                   | Commands                                                                                                                                                       |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Token and raw](Azure-Token-and-Raw)                   | `token`, `raw`                                                                                                                                                 |
| [Groups](Azure-Groups)                                 | `groups list`, `get`, `members`                                                                                                                                |
| [Users](Azure-Users)                                   | `users get`                                                                                                                                                    |
| [Applications](Azure-Applications)                     | `apps list`, `get`                                                                                                                                             |
| [Service principals](Azure-Service-Principals)         | `sp list`, `get`, `assignments`, `owners`, `add-owner`, `remove-owner`, `provision`                                                                            |
| [Entitlement management](Azure-Entitlement-Management) | `eam list-packages`, `get-package`, `delete-package`, `list-catalogs`, `get-catalog`, `list-assignments`, `add-assignment`, `remove-assignment`, `get-request` |

**AWS** — `pctl aws`

| Page                     | Commands                                         |
| ------------------------ | ------------------------------------------------ |
| [DynamoDB](AWS-DynamoDB) | `ddb tables`, `describe`, `scan`, `query`, `get` |

**OAuth 2.0** — `pctl oauth` (aliases `auth`, `auth0`)

| Page                  | Commands                                              |
| --------------------- | ----------------------------------------------------- |
| [OAuth tokens](OAuth) | `token` (client credentials), `login` (browser, PKCE) |

## What writes, and what does not

Most of `pctl` is read-only. Five commands change something, and one of those destroys
something. They are called out on every page they appear on, and collected here:

| Command                       | Effect                                          | Reversible                     |
| ----------------------------- | ----------------------------------------------- | ------------------------------ |
| `azure sp add-owner`          | Adds an owner to an Enterprise Application      | Yes, `remove-owner`            |
| `azure sp remove-owner`       | Removes one                                     | Yes, `add-owner`               |
| `azure sp provision`          | Pushes a user or group through a sync connector | N/A, it syncs rather than sets |
| `azure eam add-assignment`    | Grants an access package assignment             | Yes, `remove-assignment`       |
| `azure eam remove-assignment` | Revokes one                                     | Yes, `add-assignment`          |
| `azure eam delete-package`    | **Deletes an access package**                   | **No**                         |

`delete-package` takes its own precautions: an exact name or object ID only, a
confirmation prompt, and a check that no assignments remain. See
[Entitlement management](Azure-Entitlement-Management#delete-package).

## Design intent

- **Speed is a feature.** Lazy imports keep `pctl --help` in the low tens of milliseconds,
  tokens are cached on disk, Graph pages are prefetched, and payloads are narrowed
  server-side with `$select` and `$top` wherever the API allows it.
- **Scriptable.** Documented exit codes, four output formats, three of which stream.
- **Secrets stay out of argv.** A client secret comes from the environment or AWS Secrets
  Manager, and `--secret-id` names a secret rather than carrying one. `pctl oauth
--client-secret` is the one deliberate exception, and the [OAuth](OAuth) page says why
  to avoid it.
- **Writes are idempotent.** Re-running an `add-owner` or an `add-assignment` reports a
  no-op rather than failing, so a pipeline can be safely retried.

## Requirements

Python **3.14 or newer**. Installed and run with [uv](https://docs.astral.sh/uv/).
