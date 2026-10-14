# `pctl azure sp`

Service principals — what the Entra ID portal calls **Enterprise applications**. Four reads
and three writes.

**Aliases:** `pctl azure enterprise-apps`, `pctl azure service-principals`.

| Command        | Permission                                     | Writes |
| -------------- | ---------------------------------------------- | ------ |
| `list`         | `Application.Read.All` or `Directory.Read.All` |        |
| `get`          | `Application.Read.All` or `Directory.Read.All` |        |
| `assignments`  | `Application.Read.All` or `Directory.Read.All` |        |
| `owners`       | `Application.Read.All` or `Directory.Read.All` |        |
| `add-owner`    | `Application.ReadWrite.All` + `User.Read.All`  | ✅     |
| `remove-owner` | `Application.ReadWrite.All` + `User.Read.All`  | ✅     |
| `provision`    | `Synchronization.ReadWrite.All`                | ✅     |

> A service principal is the tenant-local instance of an
> [application registration](Azure-Applications). They share an `appId` and have different
> object IDs. If you want redirect URIs or required permissions, you want `apps`; if you want
> who has access, you want this page.

`--match` defaults to **`search`** on these commands, not `exact` as it does for
[groups](Azure-Groups). Enterprise application names are long and rarely typed exactly.

---

## `list`

| Flag                   | Default | Effect                             |
| ---------------------- | ------- | ---------------------------------- |
| `--select FIELDS`      |         | Comma-separated Graph fields       |
| `--filter ODATA`       |         | Raw OData `$filter`                |
| `--search TEXT`        |         | Full-text search on `displayName`  |
| `--starts-with PREFIX` |         | `startswith(displayName)` shortcut |
| `--app-id ID`          |         | Find the SP for a given `appId`    |
| `--order-by FIELD`     |         | Server-side ordering               |
| `-n, --limit N`        |         | Stop after N                       |
| `--page-size N`        | 999     | Graph `$top` page size             |
| `--count-only`         |         | Print just the total               |

```bash
pctl azure sp list --search "incident.io"
pctl azure sp list --app-id 00000003-0000-0000-c000-000000000000
pctl azure sp list --count-only
```

**Narrow it.** A tenant carries hundreds of service principals, most of them Microsoft
first-party applications. An unfiltered `list` is rarely what you want.

---

## `get`

| Flag                   | Default  | Effect                                        |
| ---------------------- | -------- | --------------------------------------------- |
| `--name NAME`          |          | Display name. **Repeat for several**          |
| `-f, --from-file PATH` |          | One name per line, `-` for stdin              |
| `--match MODE`         | `search` | `exact`, `prefix` or `search`                 |
| `--assignments`        |          | Attach who is assigned (`appRoleAssignedTo`)  |
| `--roles`              |          | Attach the app roles the application exposes  |
| `--assignment-limit N` |          | Cap assignments fetched per service principal |
| `--select FIELDS`      |          | Comma-separated Graph fields                  |
| `--ignore-missing`     |          | Exit 0 when a name matches nothing            |

```bash
pctl azure sp get --name "Company Incident.io SCIM"
pctl azure sp get --name "incident.io" -o json
pctl azure sp get --name "Company Incident.io SCIM" --assignments -o ndjson
pctl azure sp get --name "Company Incident.io SCIM" --roles -o json
pctl azure sp get -f apps.txt --match exact
```

`--assignments` adds an `assignmentCount` column, so a table stays readable while the full
list is still there for `-o json`.

---

## `assignments`

Who has access to an application — the question this service exists for.

| Flag                            | Default  | Effect                                  |
| ------------------------------- | -------- | --------------------------------------- |
| `--app NAME\|ID` **(required)** |          | The Enterprise Application              |
| `--match MODE`                  | `search` | How to resolve `--app`                  |
| `--principal TEXT`              |          | Keep only assignments to this principal |
| `--principal-match MODE`        | `exact`  | `exact`, `prefix` or `contains`         |
| `--outbound`                    |          | Ask the reverse question (see below)    |
| `--no-role-names`               |          | Leave `appRoleId` as a raw GUID         |
| `-n, --limit N`                 |          | Stop after N                            |

```bash
pctl azure sp assignments --app "Company Incident.io SCIM"
pctl azure sp assignments --app SCIM --principal "AWS Platform Admins"
pctl azure sp assignments --app SCIM --principal aws --principal-match contains
pctl azure sp assignments --app SCIM --outbound -o ndjson
```

### Two opposite questions, one command

| Direction    | Relationship         | Answers                                            |
| ------------ | -------------------- | -------------------------------------------------- |
| default      | `appRoleAssignedTo`  | **Who has access to this application**             |
| `--outbound` | `appRoleAssignments` | What this application has been granted access _to_ |

The default is the inbound one because it is the operational question. They are easy to
confuse, which is why they are a direction on one command rather than two similarly named
commands.

### Role names, not GUIDs

Each row gains an `appRoleName`, resolved from the roles the application itself exposes, so
`appRoleId` never reaches you as a bare GUID. The all-zero GUID renders as `Default Access`,
which is what Entra ID uses when an app exposes no roles. `--no-role-names` skips that extra
request if you do not need it.

### Scriptable access checks

```bash
if pctl azure sp assignments --app "$APP" --principal "$GROUP" -q > /dev/null; then
  echo "assigned"
else
  echo "not assigned"     # exit 4
fi
```

`--principal` defaults to **whole-name matching**, deliberately. A coincidental substring
would report access that a specific group may not have — the one place where being generous
is wrong. Widen it explicitly with `--principal-match prefix` or `contains`.

> `--principal` filters **client-side**, because Graph does not support `$filter` on
> `principalDisplayName` for this relation. Every page is fetched either way, so it narrows
> what is rendered rather than what is transferred.

`--match` and `--principal-match` are independent: the first resolves the application, the
second filters its assignments.

---

## `owners`

| Flag                            | Effect           |
| ------------------------------- | ---------------- |
| `--app NAME\|ID` **(required)** | The application  |
| `--match MODE`                  | Default `search` |
| `-n, --limit N`                 | Stop after N     |

```bash
pctl azure sp owners --app "$APP"
pctl -o ndjson azure sp owners --app "$APP" | jq -r .displayName
```

---

## `add-owner`

> **Writes.** Needs `Application.ReadWrite.All` or `Directory.ReadWrite.All`, which is broader
> than everything else here. Grant it only where owner management is actually needed.

| Flag                            | Default  | Effect                                                   |
| ------------------------------- | -------- | -------------------------------------------------------- |
| `--app NAME\|ID` **(required)** |          | The application to add owners to                         |
| `--owner VALUE`                 |          | Email, display name or object ID. **Repeat for several** |
| `--emails A@B,C@D`              |          | Comma-separated addresses, added to any `--owner`        |
| `--match MODE`                  | `search` | How to resolve `--app`                                   |
| `--owner-type`                  | `auto`   | `auto`, `user` or `sp` — where to look up an owner name  |
| `--owner-match`                 | `exact`  | `exact`, `prefix` or `search` for an owner display name  |
| `--ignore-missing`              |          | Exit 0 when an owner could not be resolved               |

```bash
pctl azure sp add-owner --app "$APP" --owner ann@company.com
pctl azure sp add-owner --app "$APP" --owner ann@company.com --owner bob@company.com
pctl azure sp add-owner --app "$APP" --emails ann@company.com,bob@company.com
pctl azure sp add-owner --app "$APP" --owner "Ann Example"
pctl azure sp add-owner --app "$APP" --owner platform-automation --owner-type sp
```

### Idempotent

The current owners are read once, and an owner who is already there is reported as
information on **exit 0** rather than as an error. Safe to re-run from a pipeline. Each owner
gets a result row:

| `status`        | Meaning                   |
| --------------- | ------------------------- |
| `added`         | The reference was created |
| `already-owner` | Nothing to do             |

```bash
pctl -o ndjson azure sp add-owner --app "$APP" --emails ann@company.com,bob@company.com \
  | jq -r '[.owner, .status] | @tsv'
```

### Only users and service principals can own one

A group **cannot** own a service principal, so groups are not searched — resolving one would
produce a valid-looking GUID that Graph then rejects. `--owner-type auto` tries users first,
since a human owner is the common case, then service principals. Pass `user` or `sp` to skip
the fallback when a name exists in both.

### Resolution is exact by default

`--owner-match` is `exact` because a prefix match on a write could name the wrong person. An
ambiguous owner name is refused rather than guessed. One unresolvable owner does not block the
others: the rest are applied and the command exits 4 unless `--ignore-missing`.

---

## `remove-owner`

Same flags as `add-owner`, same resolution, same idempotency.

```bash
pctl azure sp remove-owner --app "$APP" --owner ann@company.com
pctl azure sp remove-owner --app "$APP" --emails ann@company.com,bob@company.com
```

| `status`       | Meaning                   |
| -------------- | ------------------------- |
| `removed`      | The reference was deleted |
| `not-an-owner` | Nothing to do             |

**Warns below two owners.** Microsoft's guidance is that a service principal keeps at least
two, so losing one person does not orphan the application. The command warns and proceeds
rather than refusing:

```
Company Incident.io SCIM now has 1 owner(s). Microsoft recommends at least 2.
```

---

## `provision`

> **Writes.** Needs `Synchronization.ReadWrite.All`.

On-demand provisioning — the portal's **Provision on demand**. Pushes named users or groups
through the application's provisioning connector immediately, instead of waiting for the
40-minute sync cycle. Useful after fixing an attribute mapping, or when somebody needs access
today.

| Flag                            | Effect                                                  |
| ------------------------------- | ------------------------------------------------------- |
| `--app NAME\|ID` **(required)** | The application to provision through                    |
| `--group NAME\|ID`              | A group to provision. **Repeat for several**            |
| `--user EMAIL\|NAME\|ID`        | A user to provision. **Repeat for several**             |
| `--match MODE`                  | How to resolve `--app`. Default `search`                |
| `--job ID`                      | Synchronization job, when the app has more than one     |
| `--rule ID`                     | Synchronization rule, when the schema has more than one |
| `--ignore-missing`              | Exit 0 when a subject could not be resolved             |

At least one `--group` or `--user` is required.

```bash
pctl azure sp provision --app "$APP" --group "AWS Platform Admins"
pctl azure sp provision --app "$APP" --user ann@company.com
pctl azure sp provision --app "$APP" --group "Team A" --group "Team B"
pctl azure sp provision --app "$APP" --user ann@company.com --job "$JOB" --rule "$RULE"
```

### A 200 does not mean it worked

This is the thing to know. Graph answers `200 OK` and puts the actual verdict in a JSON
string **inside** the response body. `pctl` decodes it into an `outcome`:

| `outcome`         | Graph said                                                 | Exit |
| ----------------- | ---------------------------------------------------------- | ---- |
| `applied`         | `Success`                                                  | 0    |
| `already-in-sync` | `Skipped` with `RedundantExport` — source and target match | 0    |
| `failed`          | `Failure`, any other skip reason, or anything unrecognised | 5    |

Other skip reasons count as **failures** on purpose. A subject that is out of scope or not
assigned to the application comes back as `Skipped` with nothing provisioned, and reporting
that as success would be the worst possible lie here. An unrecognised verdict is also a
failure: this command is usually run because something is already wrong.

```bash
pctl -o ndjson azure sp provision --app "$APP" --group "$GROUP" \
  | jq -r '[.subject, .outcome, .detail] | @tsv'
```

### Job and rule are discovered

With exactly one synchronization job and one rule, neither flag is needed. With more than one
the command lists the candidates and refuses, because provisioning through the wrong rule
writes the wrong attributes.

An application with **no** synchronization job exits **2** saying provisioning is not enabled
— that includes the 404 Graph returns when the app has no `synchronization` segment at all. A
**403** deliberately does not say that: it means the token lacks
`Synchronization.ReadWrite.All`, and calling it "not enabled" would send you to the portal to
fix the wrong thing.

`--rule` takes the ID as the schema reports it, which is not always a bare GUID — a versioned
rule looks like `33f7c90d-bf71-41b1-bda6-aaf0ddbee5d8#V2`.

### One request per subject, sequentially

Graph rate limits this action to **5 requests every 10 seconds**, far tighter than the rest of
the API, so a concurrent batch would simply be throttled. One request per subject is also what
makes the per-subject outcome possible: the response carries a single verdict, so batching
would report one result for several people.

---

## Recipes

```bash
# every principal assigned to an app, as TSV
pctl -o ndjson azure sp assignments --app "$APP" \
  | jq -r '[.principalDisplayName, .appRoleName] | @tsv'

# which apps does this group have access to (inbound check, per app)
pctl azure sp list --starts-with "Company " -o ndjson | jq -r .displayName \
  | while read -r app; do
      pctl azure sp assignments --app "$app" --principal "$GROUP" -q > /dev/null \
        && echo "$app"
    done

# owners of every app matching a prefix
pctl azure sp list --starts-with "Company " -o ndjson | jq -r .displayName \
  | while read -r app; do
      echo "== $app"; pctl azure sp owners --app "$app" -c displayName -q
    done
```

## Related

- [Applications](Azure-Applications) — the registration behind each of these
- [Users](Azure-Users) — how an owner or subject name is resolved
- [Permissions](Permissions)
- [Output and exit codes](Output-and-Exit-Codes)
