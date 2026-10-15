# Common options

Flags that recur across commands, documented once. Per-command pages list only what is
specific to them.

## Global

Accepted **before the case** or **on the leaf command**, not in between.

| Flag                | Default | Effect                                |
| ------------------- | ------- | ------------------------------------- |
| `-o, --output`      | `table` | `table`, `json`, `ndjson` or `csv`    |
| `-q, --quiet`       | off     | Suppress the result summary on stderr |
| `-v, --verbose`     | off     | Log progress to stderr                |
| `--timeout SECONDS` | `30`    | Per-request timeout                   |
| `--concurrency N`   | `16`    | Maximum in-flight Graph requests      |
| `-V, --version`     |         | Print the version                     |
| `-h, --help`        |         | Help, at every level                  |

`-v` is the first thing to reach for when something is slow or surprising: it prints which
names are being resolved, how many requests are in flight, and every retry.

## Credentials

### Graph — on every `azure` command

| Flag               | Environment            | Notes                                                      |
| ------------------ | ---------------------- | ---------------------------------------------------------- |
| `--tenant-id ID`   | `AZURE_TENANT_ID`      | GUID or domain                                             |
| `--client-id ID`   | `AZURE_CLIENT_ID`      | App registration (client) ID                               |
| `--secret-id NAME` | `PCTL_AZURE_SECRET_ID` | Reads `client_id`/`client_secret` from AWS Secrets Manager |
| `--secret-region`  |                        | Region holding that secret. Default `eu-central-1`         |
| `--scope SCOPE`    |                        | Default `https://graph.microsoft.com/.default`             |
| `--no-token-cache` | `PCTL_NO_TOKEN_CACHE`  | Do not read or write the on-disk token cache               |

**`azure` has no `--client-secret`.** Use `AZURE_CLIENT_SECRET` or `--secret-id`. Flags land
in shell history and `ps` output. `oauth` is the one exception; see [OAuth](OAuth).

### AWS — on every `aws` command

| Flag                 | Environment   | Notes                                                 |
| -------------------- | ------------- | ----------------------------------------------------- |
| `--profile NAME`     | `AWS_PROFILE` | Shared-config profile                                 |
| `--region REGION`    | `AWS_REGION`  |                                                       |
| `--endpoint-url URL` |               | Point at local DynamoDB, e.g. `http://localhost:8000` |

## Narrowing what comes back

| Flag                 | Where                       | Runs                     |
| -------------------- | --------------------------- | ------------------------ |
| `--select FIELDS`    | most reads                  | server-side              |
| `-n, --limit N`      | every list and stream       | client-side, stops early |
| `--page-size N`      | lists                       | server-side `$top`       |
| `-c, --columns COLS` | `table` and `csv` rendering | local                    |

`--select` reduces bytes transferred; `-c/--columns` only changes what is displayed. Use
`--select` for cost, `--columns` for readability.

## Matching a name

Two different vocabularies, because two different APIs.

**`groups` and `sp`** — `--match exact | prefix | search`

| Mode     | Sends                           | Notes                                  |
| -------- | ------------------------------- | -------------------------------------- |
| `exact`  | `displayName eq '...'`          | Default for `groups`                   |
| `prefix` | `startswith(displayName,'...')` |                                        |
| `search` | Graph `$search`, substring      | Default for `sp`, whose names are long |

**`eam`** — `--match exact | prefix | contains`

| Mode       | Runs        | Notes                                                 |
| ---------- | ----------- | ----------------------------------------------------- |
| `exact`    | server-side | Default                                               |
| `prefix`   | server-side | `startswith`                                          |
| `contains` | **locally** | Entitlement management supports no substring operator |

There is deliberately no `search` in `eam`: `$search` does not exist on those collections, so
offering it would be a promise the API breaks. `contains` is honest about fetching the
collection and filtering in the client.

`eam delete-package` has **no `--match` at all** — see
[Entitlement management](Azure-Entitlement-Management#delete-package).

## Naming several things

Repeat the flag rather than separating with commas, because a display name may legitimately
contain one:

```bash
pctl azure groups get --name "Team A" --name "Team B"
pctl azure sp add-owner --app "$APP" --owner ann@example.com --owner bob@example.com
```

`--emails` is the exception, and is comma-separated by design — an address cannot contain a
comma:

```bash
pctl azure sp add-owner --app "$APP" --emails ann@example.com,bob@example.com
```

`-f, --from-file PATH` reads one value per line on the four `get` commands, ignoring blanks
and `#` comments, and merges with any flag values. `-` reads stdin:

```bash
pctl azure groups get -f my-groups.txt --counts
pctl azure groups list -o ndjson | jq -r .displayName | pctl azure groups get -f -
```

## Tolerating misses

`--ignore-missing` exits 0 when a name matched nothing, instead of 4. Offered on the reads
that take several values, and on the writes.

It does **not** tolerate an ambiguous name, which exits 2 either way. Skipping a name that
matched two people would drop one of them silently.

## Confirming a write applied

On `eam add-assignment`, `eam remove-assignment` and `eam get-request`:

| Flag                     | Default | Effect                                                       |
| ------------------------ | ------- | ------------------------------------------------------------ |
| `--wait`                 | off     | Poll until the request settles; exit 5 if it did not apply   |
| `--wait-timeout SECONDS` | `120`   | Give up waiting. Still-pending is reported, not assumed good |

Without `--wait`, exit 0 means the request was _accepted_, not that access exists. See
[Entitlement management](Azure-Entitlement-Management#knowing-whether-it-applied).

## Related

- [Output and exit codes](Output-and-Exit-Codes)
- [Permissions](Permissions)
