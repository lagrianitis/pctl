# `pctl aws ddb`

Read items and metadata from DynamoDB tables. **Every command here is read-only** — nothing
in `pctl aws` writes, deletes or modifies a table.

**Permission:** IAM on the table, one action per command. See
[Permissions](Permissions#aws) for a policy covering all five.

```bash
pctl aws ddb --help
```

Credentials resolve through the standard boto3 chain, so profiles, SSO, assumed roles and
instance credentials behave exactly as they do with the AWS CLI. `--profile`, `--region` and
`--endpoint-url` are accepted on every command — see
[Common options](Common-Options#aws--on-every-aws-command).

### The alias trap

At the root, `ddb` is an alias for the **case** `aws` — not a shortcut past it. So
`pctl ddb tables` expands to `pctl aws tables`, and fails, because `tables` is a subcommand of
`ddb`, not of `aws`:

```bash
pctl ddb tables      # ✗  becomes `pctl aws tables`
pctl ddb scan        # ✗  same reason
pctl aws ddb tables  # ✓
```

The alias buys you nothing here. Type `aws ddb`.

---

## `tables`

Every table in the account and region. Takes no flags beyond credentials and output.

```bash
pctl aws ddb tables
pctl aws ddb tables --profile platform-dev --region eu-central-1
pctl aws ddb tables -o ndjson | jq -r .table
```

**IAM:** `dynamodb:ListTables`, which cannot be scoped to a table — it is account-level, so
the policy needs `"Resource": "*"` for this command and only for this one.

Output is a single `table` column, so it pipes straight into a loop:

```bash
pctl aws ddb tables -o ndjson | jq -r .table | while read -r name; do
  pctl aws ddb describe --table "$name" -o json > "$name.json"
done
```

---

## `describe`

Keys, indexes, item count and size for one table.

| Flag                          | Effect    |
| ----------------------------- | --------- |
| `--table NAME` **(required)** | The table |

```bash
pctl aws ddb describe --table my-table
pctl aws ddb describe --table my-table -o json
```

**IAM:** `dynamodb:DescribeTable`.

### Table output is a summary

`-o table` renders six fields — name, status, item count, size in bytes, key schema and index
names. The full `DescribeTable` payload is much larger, and you get all of it with `-o json`:

```bash
pctl aws ddb describe --table my-table -o json | jq '.GlobalSecondaryIndexes[].IndexName'
```

That difference is deliberate: the summary is for reading, the JSON is for scripting.

### `ItemCount` is approximate

DynamoDB updates it roughly every six hours, so treat it as an order of magnitude rather than
a count. If you need the real number, `scan --projection` the key and count the lines:

```bash
pctl aws ddb scan --table my-table --projection pk -o ndjson | wc -l
```

---

## `scan`

Read the whole table, streaming items as they arrive.

| Flag                          | Default   | Effect                                                        |
| ----------------------------- | --------- | ------------------------------------------------------------- |
| `--table NAME` **(required)** |           | The table                                                     |
| `--index NAME`                |           | Scan a secondary index instead of the table                   |
| `--projection EXPR`           |           | `ProjectionExpression` — fetch only these attributes          |
| `--filter EXPR`               |           | `FilterExpression`, applied **after** the read                |
| `--names JSON`                |           | `ExpressionAttributeNames`, e.g. `'{"#s":"status"}'`          |
| `--values JSON`               |           | Expression values as **plain** JSON, e.g. `'{":s":"ACTIVE"}'` |
| `--consistent`                | off       | Strongly consistent read                                      |
| `--page-size N`               |           | Items per page, 1–1000                                        |
| `-n, --limit N`               |           | Stop after N items                                            |
| `--segments N`                | see below | Parallel scan segments, 1–64                                  |

Plus the [credential, column and global options](Common-Options).

```bash
pctl aws ddb scan --table my-table -n 20
pctl aws ddb scan --table my-table --segments 8 -o ndjson > items.ndjson
pctl aws ddb scan --table my-table --filter "#s = :s" \
    --names '{"#s":"status"}' --values '{":s":"ACTIVE"}'
```

**IAM:** `dynamodb:Scan`. Scanning an index needs the index in the resource ARN.

### A scan reads the whole table

It costs read capacity proportional to the table's **size**, not to how many items come back.
`--filter` does not change that: DynamoDB reads the item, then discards it. A filtered scan
returning three items from a 10 GB table still pays for 10 GB.

Use [`query`](#query) whenever the partition key is known. Reach for `scan` when it is not.

`--projection` genuinely helps, because it reduces the bytes crossing the network — though not
the capacity consumed.

### `--segments`

DynamoDB splits the key space into `TotalSegments` and lets you read them independently.
`pctl` runs one thread per segment against a shared client, pushing pages onto a bounded queue
that the renderer drains lazily, so memory stays flat while later segments are still in flight.

The default is chosen for you:

| Situation         | Default segments    |
| ----------------- | ------------------- |
| with `-n/--limit` | **1**               |
| otherwise         | `min(8, CPU count)` |

One segment is usually network-bound, so a few threads help. Many more just burn read
capacity faster without finishing much sooner. The ceiling is **64**.

With `--limit`, one segment is deliberate: parallel segments each fetch a full page, so eight
of them overfetch eight pages to hand you twenty items.

```bash
pctl aws ddb scan --table my-table --segments 16 -o ndjson > items.ndjson   # big export
pctl aws ddb scan --table my-table -n 5                                     # 1 segment
pctl aws ddb scan --table my-table --segments 8 -v                          # watch the pages
```

`-v` logs each page as it lands and the segment count it started with, which is the quickest
way to see whether the parallelism is helping.

### Streaming

Items are written as they arrive, so `-o ndjson` and `-o csv` keep memory flat on a table of
any size. `head` on the pipe exits 141 cleanly rather than raising a broken-pipe traceback:

```bash
pctl aws ddb scan --table my-table -o ndjson | head -5
```

`-o json` streams as well, holding back only the first record so that a lone result renders as
an object. `-o table` is the one that buffers, because column widths are not known until the
last row — so avoid it for a full export.

### Expression attribute names and values

`--filter`, `--projection` and `--key` are raw DynamoDB expressions, so the same rules apply as
in the API. Reserved words and attributes containing a `.` or `-` need a placeholder:

```bash
# "status" and "size" are reserved words
pctl aws ddb scan --table my-table --filter "#s = :s AND #sz > :n" \
    --names '{"#s":"status","#sz":"size"}' \
    --values '{":s":"ACTIVE",":n":100}'
```

**`--values` takes plain JSON, not DynamoDB-typed JSON.** `pctl` serialises it for you:

```bash
--values '{":s":"ACTIVE"}'              # what pctl wants
--values '{":s":{"S":"ACTIVE"}}'        # the API's shape, also accepted
```

Both work — a payload that already looks typed is passed through untouched. Plain is shorter,
so prefer it.

Single-quote these, always. `$`, `!` and `{` all mean something to the shell, and zsh in
particular will expand `!` inside double quotes.

---

## `query`

Read by key condition. Cheaper and faster than a scan whenever the partition key is known.

| Flag                          | Default | Effect                                              |
| ----------------------------- | ------- | --------------------------------------------------- |
| `--table NAME` **(required)** |         | The table                                           |
| `--key EXPR` **(required)**   |         | `KeyConditionExpression`                            |
| `--index NAME`                |         | Query a secondary index                             |
| `--desc`                      | off     | Descending sort order                               |
| `--projection EXPR`           |         | Fetch only these attributes                         |
| `--filter EXPR`               |         | `FilterExpression`, applied after the key condition |
| `--names JSON`                |         | `ExpressionAttributeNames`                          |
| `--values JSON`               |         | Expression values as plain JSON                     |
| `--consistent`                | off     | Strongly consistent read                            |
| `--page-size N`               |         | Items per page, 1–1000                              |
| `-n, --limit N`               |         | Stop after N items                                  |

Plus the [credential, column and global options](Common-Options).

```bash
pctl aws ddb query --table my-table --key "pk = :pk" --values '{":pk":"tenant#42"}'
pctl aws ddb query --table my-table --key "pk = :pk AND begins_with(sk, :prefix)" \
    --values '{":pk":"tenant#42",":prefix":"order#"}'
pctl aws ddb query --table my-table --index gsi1 --key "gsi1pk = :p" \
    --values '{":p":"ACTIVE"}' --desc -n 10
```

**IAM:** `dynamodb:Query`, plus the index ARN when using `--index`.

### `--key` versus `--filter`

The distinction is the whole reason to use `query`:

|            | Runs                           | Costs                           |
| ---------- | ------------------------------ | ------------------------------- |
| `--key`    | inside DynamoDB's index lookup | only the matching items         |
| `--filter` | after the items are read       | every item read, matched or not |

So put everything you can into `--key`. The key condition may use `=` on the partition key,
and `=`, `<`, `<=`, `>`, `>=`, `BETWEEN` or `begins_with()` on the sort key. Anything else
belongs in `--filter`.

### `--desc` and no `--segments`

`--desc` sets `ScanIndexForward=False`, reversing the sort-key order within the partition.
Useful for "most recent first" when the sort key is a timestamp.

There is no `--segments` on `query`: parallel segments exist for scans, and a query is already
a targeted read.

### Consistent reads

`--consistent` doubles the capacity cost and is not available on a global secondary index —
DynamoDB rejects the combination, which surfaces as exit 5 with a `ValidationException`
message. Use it on the table, or on a local secondary index.

---

## `get`

Fetch one item by primary key.

| Flag                          | Effect                       |
| ----------------------------- | ---------------------------- |
| `--table NAME` **(required)** | The table                    |
| `--key JSON` **(required)**   | Primary key as a JSON object |
| `--projection EXPR`           | Fetch only these attributes  |
| `--consistent`                | Strongly consistent read     |

Plus the [credential and global options](Common-Options).

```bash
pctl aws ddb get --table my-table --key '{"pk":"tenant#42","sk":"profile"}'
pctl aws ddb get --table my-table --key '{"pk":{"S":"tenant#42"}}'
pctl aws ddb get --table my-table --key '{"pk":"tenant#42"}' --projection "pk,email" -o json
```

**IAM:** `dynamodb:GetItem`.

### `--key` is JSON, plain or typed

Unlike `query --key`, which is an expression, `get --key` is the key **itself** as a JSON
object. Both shapes are accepted:

```bash
--key '{"pk":"tenant#42","sk":"profile"}'            # plain
--key '{"pk":{"S":"tenant#42"},"sk":{"S":"profile"}}' # DynamoDB-typed
```

It must include every key attribute — both the partition and sort key on a composite-key
table. A partial key is a `ValidationException` from DynamoDB, not a local error.

An empty or non-object `--key` is a usage error, exit 2. A key that matches nothing exits
**4**, so `get` is usable as an existence check:

```bash
if pctl aws ddb get --table my-table --key '{"pk":"x"}' -q > /dev/null 2>&1; then
  echo present
fi
```

---

## Local DynamoDB

`--endpoint-url` points every command at a local instance, which is the cheapest way to try a
scan or a filter expression without touching a real table:

```bash
podman run --rm -p 8000:8000 amazon/dynamodb-local

export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_REGION=eu-central-1
pctl aws ddb tables --endpoint-url http://localhost:8000
pctl aws ddb scan --table my-table --endpoint-url http://localhost:8000
```

Local DynamoDB still wants credentials to exist, but does not check them, so any dummy values
work. A region is required — without one you get exit 2 and
`No AWS region configured`.

---

## Failures

| Exit | Cause                                                                                     |
| ---- | ----------------------------------------------------------------------------------------- |
| 2    | No region configured, no credentials resolvable, bad JSON in `--key`/`--values`/`--names` |
| 4    | Table or index not found; `get` matched no item                                           |
| 5    | Access denied, expired credentials, or DynamoDB rejected the request                      |
| 141  | The pipe closed early, as with `head`                                                     |

A `ValidationException` is reported as exit 5 with DynamoDB's own message, which is usually
precise about what it objected to — a missing key attribute, a placeholder used but not
defined, `--consistent` on a global index.

Throttling is not in this table because you should not see it: the client retries with
adaptive mode and up to eight attempts, so brief throttling is absorbed. Sustained throttling
on a scan means `--segments` is too high for the table's provisioned capacity.

---

## Recipes

```bash
# every table's size, as a CSV
pctl aws ddb tables -o ndjson | jq -r .table | while read -r name; do
  pctl aws ddb describe --table "$name" -o json |
    jq -r '[.TableName, .ItemCount, .TableSizeBytes] | @csv'
done

# export a table, fast
pctl aws ddb scan --table my-table --segments 16 -o ndjson > my-table.ndjson

# count the items matching a filter, without holding them in memory
pctl aws ddb scan --table my-table --projection pk \
    --filter "#s = :s" --names '{"#s":"status"}' --values '{":s":"ACTIVE"}' \
    -o ndjson | wc -l

# the ten most recent rows in a partition
pctl aws ddb query --table my-table --key "pk = :pk" \
    --values '{":pk":"tenant#42"}' --desc -n 10 -o table

# one item, one attribute
pctl aws ddb get --table my-table --key '{"pk":"tenant#42","sk":"profile"}' \
    --projection email -o json | jq -r .email
```

## Related

- [Permissions](Permissions#aws) — the IAM policy, including the index ARN
- [Common options](Common-Options#aws--on-every-aws-command) — `--profile`, `--region`, `--endpoint-url`
- [Output and exit codes](Output-and-Exit-Codes) — the four formats, and which of them buffer
- [Troubleshooting](Troubleshooting)
