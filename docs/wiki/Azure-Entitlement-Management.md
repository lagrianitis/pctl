# `pctl azure eam`

Entra ID entitlement management: access packages, the catalogs that hold them, and who is
assigned to them. Six reads, two writes and one delete.

**Aliases:** `pctl azure entitlement-management`, `pctl azure access-packages`.

| Command             | Permission                            | Writes |
| ------------------- | ------------------------------------- | ------ |
| `list-packages`     | `EntitlementManagement.Read.All`      |        |
| `get-package`       | `EntitlementManagement.Read.All`      |        |
| `list-catalogs`     | `EntitlementManagement.Read.All`      |        |
| `get-catalog`       | `EntitlementManagement.Read.All`      |        |
| `list-assignments`  | `EntitlementManagement.Read.All`      |        |
| `get-request`       | `EntitlementManagement.Read.All`      |        |
| `add-assignment`    | `EntitlementManagement.ReadWrite.All` | ✅     |
| `remove-assignment` | `EntitlementManagement.ReadWrite.All` | ✅     |
| `delete-package`    | `EntitlementManagement.ReadWrite.All` | 💥     |

---

## A narrower query surface

These collections live under `identityGovernance/entitlementManagement` and support **less**
OData than the rest of Graph. It shapes every command here:

| Supported                       | Not supported       |
| ------------------------------- | ------------------- |
| `$select`, `$filter`, `$expand` | `$search`, `$count` |

Consequences worth knowing up front:

- There is **no `--search`** and **no `--count-only`** in this service.
- `--match` offers `exact | prefix | contains`, not `search`. `contains` filters **locally**
  after fetching the collection, because Graph has no substring operator here — the help text
  says so rather than implying a round trip that never happens.
- `--contains` on the list commands is the same story.

Asking for an unsupported parameter does not get ignored; Graph rejects the whole request with
a 400. That is why this service has its own query builder rather than reusing the directory
one.

---

## `list-packages`

| Flag                   | Default | Effect                                            |
| ---------------------- | ------- | ------------------------------------------------- |
| `--catalog NAME\|ID`   |         | Only packages in this catalog                     |
| `--name TEXT`          |         | Server-side exact `displayName` match             |
| `--starts-with PREFIX` |         | Server-side `startswith(displayName)`             |
| `--contains TEXT`      |         | Keep names containing TEXT — **filtered locally** |
| `--filter ODATA`       |         | Raw OData `$filter`                               |
| `--select FIELDS`      |         | Comma-separated Graph fields                      |
| `-n, --limit N`        |         | Stop after N                                      |
| `--page-size N`        | 999     | Graph `$top` page size                            |

```bash
pctl azure eam list-packages
pctl azure eam list-packages --name "AWS Platform Access"
pctl azure eam list-packages --starts-with "AWS"
pctl azure eam list-packages --contains platform
pctl azure eam list-packages --catalog "AWS Platform"
```

`--catalog` takes a **name or an ID**: a name is resolved to the ID the filter needs, so you
do not have to look it up first. A raw `--filter` takes precedence over `--catalog`,
`--name` and `--starts-with` — someone who wrote OData by hand means it.

`-n/--limit` is applied **after** a local `--contains` filter, so a cap cannot drop real
matches.

---

## `get-package`

| Flag                                       | Default | Effect                                   |
| ------------------------------------------ | ------- | ---------------------------------------- |
| `--access-package NAME\|ID` **(required)** |         | Display name, name pattern, or object ID |
| `--match MODE`                             | `exact` | `exact`, `prefix` or `contains`          |
| `--with-policies`                          |         | Expand the assignment policies           |
| `--select FIELDS`                          |         | Comma-separated Graph fields             |

```bash
pctl azure eam get-package --access-package "AWS Platform Access"
pctl azure eam get-package --access-package AWS --match prefix -o ndjson
pctl azure eam get-package --access-package incident --match contains
pctl azure eam get-package --access-package "AWS Platform Access" --with-policies
pctl azure eam get-package --access-package a914b616-e04e-476b-aa37-91038f0b165b
```

### It takes patterns, and returns every match

`prefix` and `contains` are patterns, so they return **every** match rather than refusing an
ambiguous one — "show me the AWS packages" is a question with several answers. One match
renders as an object and several as an array, the same shape
[`groups get`](Azure-Groups#get) uses, so `jq` needs no index in the common case. An object ID
is not a pattern and always returns exactly one.

`--with-policies` expands `assignmentPolicies`, where the approval and expiry rules live. That
is also where you find the policy ID that
[`add-assignment --policy`](#add-assignment) wants.

---

## `list-catalogs` and `get-catalog`

`list-catalogs` takes the same list options as `list-packages`, minus `--catalog`.
`get-catalog` mirrors `get-package`:

| Flag                                | Default | Effect                              |
| ----------------------------------- | ------- | ----------------------------------- |
| `--catalog NAME\|ID` **(required)** |         | Display name, pattern, or object ID |
| `--match MODE`                      | `exact` | `exact`, `prefix` or `contains`     |
| `--select FIELDS`                   |         | Comma-separated Graph fields        |

```bash
pctl azure eam list-catalogs
pctl azure eam get-catalog --catalog "AWS Platform"
pctl azure eam get-catalog --catalog aws --match contains
```

---

## `list-assignments`

Who is assigned to an access package.

| Flag                        | Default | Effect                                                     |
| --------------------------- | ------- | ---------------------------------------------------------- |
| `--access-package NAME\|ID` |         | Only assignments to this package                           |
| `--state STATE`             |         | One of the assignment states below                         |
| `--target TEXT`             |         | Keep targets whose name or email contains TEXT — **local** |
| `--filter ODATA`            |         | Raw OData `$filter`                                        |
| `--no-expand`               |         | Leave the relationship IDs unexpanded                      |
| `--select FIELDS`           |         | Comma-separated Graph fields                               |
| `-n, --limit N`             |         | Stop after N                                               |
| `--page-size N`             | 999     | Graph `$top` page size                                     |

```bash
pctl azure eam list-assignments --access-package "AWS Platform Access"
pctl azure eam list-assignments --access-package "$PKG" --state Delivered
pctl azure eam list-assignments --state Expired -o ndjson
pctl azure eam list-assignments --access-package "$PKG" --target ann@
pctl -o ndjson azure eam list-assignments --access-package "$PKG" --state Delivered \
  | jq -r '[.targetDisplayName, .targetEmail] | @tsv'
```

### States

`Delivering`, `PartiallyDelivered`, `Delivered`, `Expired`, `DeliveryFailed`. **Case matters**
in the filter, so these are the exact spellings.

`--state Delivered` is the usual question: who has _live_ access right now.

### Expanded names

`target` and `accessPackage` are expanded by default, and their names lifted to the top level
as `targetDisplayName`, `targetEmail` and `accessPackageName`, so a table or CSV can address
them — a column cannot reach `target.displayName`. The nested objects stay intact for `json`
and `ndjson`; these are additions, not replacements. `--no-expand` skips it and leaves the raw
relationship IDs.

---

## `add-assignment`

> **Writes.** Needs `EntitlementManagement.ReadWrite.All`.

| Flag                                       | Default | Effect                                                     |
| ------------------------------------------ | ------- | ---------------------------------------------------------- |
| `--access-package NAME\|ID` **(required)** |         | The package to assign                                      |
| `--target EMAIL\|NAME\|ID`                 |         | Person to assign. **Repeat for several**                   |
| `--emails A@B,C@D`                         |         | Comma-separated addresses, added to any `--target`         |
| `--policy NAME\|ID`                        |         | Which assignment policy governs it                         |
| `--wait`                                   | off     | Poll until the request settles; exit 5 if it did not apply |
| `--wait-timeout SECONDS`                   | 120     | Give up waiting                                            |
| `--ignore-missing`                         |         | Exit 0 when a person could not be resolved                 |

At least one `--target` or `--emails` is required.

```bash
pctl azure eam add-assignment --access-package "$PKG" --target ann@company.com
pctl azure eam add-assignment --access-package "$PKG" --target ann@company.com --wait
pctl azure eam add-assignment --access-package "$PKG" --emails a@b.com,c@d.com --wait
pctl azure eam add-assignment --access-package "$PKG" --target a@b.com --policy Direct
```

### Assignments are not written directly

Both writes create an
[`accessPackageAssignmentRequest`](https://learn.microsoft.com/en-us/graph/api/entitlementmanagement-post-assignmentrequests)
which Graph processes **asynchronously**. Without `--wait` the command returns a `requestId`
and the state at submission — which is _not_ access yet, and exit 0 does not mean the change
is live.

### Idempotent

Existing assignments are read first. Someone who already has live access is reported rather
than re-requested:

| `status`           | Meaning                                   |
| ------------------ | ----------------------------------------- |
| `requested`        | A request was created                     |
| `already-assigned` | Live access already exists, nothing to do |

Expired assignments do **not** block a fresh add, because an expired assignment is not access.

### The policy

An `adminAdd` must reference a policy, and a package can have several with different approval
and expiry rules. So:

- `--policy` wins if given, by name or ID.
- Exactly one policy is used without asking.
- More than one is **refused**, with the names listed. Picking arbitrarily would silently grant
  access under the wrong rules.

Find them with `get-package --with-policies`.

---

## `remove-assignment`

Same flags as `add-assignment`, minus `--policy` — an `adminRemove` names the existing
assignment rather than the rules that created it.

```bash
pctl azure eam remove-assignment --access-package "$PKG" --target ann@company.com --wait
pctl azure eam remove-assignment --access-package "$PKG" --emails a@b.com,c@d.com --wait
```

| `status`            | Meaning                           |
| ------------------- | --------------------------------- |
| `removal-requested` | A request was created             |
| `not-assigned`      | No live assignment, nothing to do |

**`--wait` matters more here than for add.** If you are revoking access in response to an
incident, exit 0 without `--wait` does not mean the access is gone.

---

## Knowing whether it applied

`--wait` polls each request until it settles and exits **5** if any did not reach `delivered`,
bounded by `--wait-timeout`. Each record gains an `outcome`:

| `outcome` | Raw state                                        | Exit                             |
| --------- | ------------------------------------------------ | -------------------------------- |
| `done`    | `delivered`                                      | 0                                |
| `failed`  | `denied`, `canceled`, `deliveryFailed`           | 5                                |
| `partial` | `partiallyDelivered`                             | 5                                |
| `pending` | anything else, **including unrecognised states** | 0, or 5 with `--fail-on-pending` |

Unrecognised counts as **pending, never done**. A request can sit in `delivering` indefinitely
when provisioning is stuck, so treating an unknown state as finished would report success for
access that never arrived.

`partial` is reported distinctly because Microsoft's guidance is to _reprocess_ those rather
than resubmit them.

### `get-request`

Check a request submitted earlier — that is what the `requestId` is for.

| Flag                             | Default | Effect                                                        |
| -------------------------------- | ------- | ------------------------------------------------------------- |
| `--request-id ID` **(required)** |         | The ID returned by a write                                    |
| `--wait`                         | off     | Poll until it settles rather than reporting the current state |
| `--wait-timeout SECONDS`         | 120     | Give up waiting                                               |
| `--fail-on-pending`              |         | Exit 5 when it has not settled, instead of 0                  |

```bash
pctl azure eam get-request --request-id 4c2a1f7e-...
pctl azure eam get-request --request-id 4c2a1f7e-... --wait
pctl azure eam get-request --request-id 4c2a1f7e-... --wait --fail-on-pending
```

Reports `requestorName` — on a direct assignment the requestor **is** the person assigned,
which is what `adminAdd` and `adminRemove` create.

---

## `delete-package`

> 💥 **The only destructive command in `pctl`.** Deleting takes the package's policies,
> resource role assignments and request history with it. If you only want it out of the
> catalog, **hiding it is reversible and this is not.**

| Flag                                       | Effect                                                       |
| ------------------------------------------ | ------------------------------------------------------------ |
| `--access-package NAME\|ID` **(required)** | Exact display name or object ID                              |
| `--yes`                                    | Skip the confirmation. Required when stdin is not a terminal |
| `--force`                                  | Skip the assignment pre-check and let Graph decide           |

```bash
pctl azure eam delete-package --access-package "Retired Access"          # prompts
pctl azure eam delete-package --access-package "Retired Access" --yes    # for pipelines
pctl azure eam delete-package --access-package a914b616-... --yes
```

It behaves differently from its neighbours in three deliberate ways.

### No `--match`, and no substring fallback

Every other `eam` command resolves a name loosely to be helpful — `get-package` even falls
back to a substring match when an exact name finds nothing. This one takes an **exact display
name or an object ID**, nothing else, because `Retired` quietly resolving to `Retired Access`
is not a mistake worth risking. Two packages sharing a name are refused with both IDs listed.
An object ID is fetched before use, so a typo fails as a lookup rather than as a delete.

### It asks first

The prompt comes **after** resolution, so it names the package and ID about to go:

```
Delete access package 'Retired Access' (a914b616-...)? This cannot be undone. [y/N]
```

Declining aborts **non-zero**, so a wrapper cannot read a refused delete as a successful one.
`--yes` skips it and is required in a pipeline, where stdin is not a terminal.

### It checks for assignments

Graph [will not delete a package](https://learn.microsoft.com/en-us/graph/api/accesspackage-delete)
that has **any** `accessPackageAssignment`. Rather than return a bare 400, this checks first
and tells you what is in the way:

```
'AWS Platform Access' still has 3 assignment(s) (2 Delivered, 1 Expired), and Graph will not
delete a package that has any. Remove them first with `pctl azure eam remove-assignment`, or
pass --force to try the delete anyway.
```

`--force` skips only that pre-check and lets Graph decide — useful if you think the check is
over-cautious. It does **not** skip the confirmation; the two flags guard different things.

---

## Recipes

```bash
# who has live access to a package
pctl -o ndjson azure eam list-assignments --access-package "$PKG" --state Delivered \
  | jq -r '[.targetDisplayName, .targetEmail] | @tsv'

# grant, confirm, and fail the pipeline if it did not land
pctl azure eam add-assignment --access-package "$PKG" --target "$WHO" --wait || exit 1

# every package in a catalog, with its ID
pctl -o ndjson azure eam list-packages --catalog "$CATALOG" \
  | jq -r '[.displayName, .id] | @tsv'

# find the policy IDs a package offers
pctl -o json azure eam get-package --access-package "$PKG" --with-policies \
  | jq -r '.assignmentPolicies[] | [.displayName, .id] | @tsv'

# empty a package, then delete it
pctl -o ndjson azure eam list-assignments --access-package "$PKG" --state Delivered \
  | jq -r .targetEmail \
  | while read -r who; do
      pctl azure eam remove-assignment --access-package "$PKG" --target "$who" --wait
    done
pctl azure eam delete-package --access-package "$PKG" --yes
```

## Related

- [Users](Azure-Users) — how a `--target` is resolved
- [Output and exit codes](Output-and-Exit-Codes)
- [Permissions](Permissions)
- [Troubleshooting](Troubleshooting)
