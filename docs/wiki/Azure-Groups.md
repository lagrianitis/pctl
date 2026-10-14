# `pctl azure groups`

Entra ID groups: list the tenant, resolve groups by display name, stream their members and
owners. All three are read-only.

**Permission:** `Group.Read.All`, plus `User.Read.All` wherever members or owners are
fetched.

```bash
pctl azure groups --help
```

---

## `list`

Every group in the tenant, following `@odata.nextLink`.

| Flag                   | Default | Effect                                                      |
| ---------------------- | ------- | ----------------------------------------------------------- |
| `--select FIELDS`      |         | Comma-separated Graph fields. Fewer fields is faster        |
| `--filter ODATA`       |         | Raw OData `$filter`                                         |
| `--search TEXT`        |         | Graph full-text search on `displayName`, matches substrings |
| `--starts-with PREFIX` |         | Shortcut for a `startswith(displayName)` filter             |
| `--order-by FIELD`     |         | Server-side ordering                                        |
| `-n, --limit N`        |         | Stop after N groups                                         |
| `--page-size N`        | 999     | Graph `$top` page size                                      |
| `--count-only`         |         | Print just the total                                        |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure groups list
pctl azure groups list -o ndjson > groups.ndjson
pctl azure groups list --starts-with "aws-" --limit 50
pctl azure groups list --search platform -c displayName,mail
pctl azure groups list --count-only
```

### Narrowing server-side matters

A large tenant has thousands of groups. `--starts-with`, `--search` and `--filter` are all
applied by Graph, so they reduce what crosses the network; `--select` reduces the bytes per
record. `-n/--limit` only stops the client early, after the pages have been fetched.

`--page-size` defaults to 999, Graph's maximum, because the round trips dominate.

### `--count-only`

Uses Graph's `$count` rather than paging the collection, so it stays cheap on a tenant of any
size:

```bash
pctl azure groups list --count-only
pctl azure groups list --starts-with aws- --count-only
```

---

## `get`

Details for one or more groups, resolved by display name.

| Flag                   | Default | Effect                                                      |
| ---------------------- | ------- | ----------------------------------------------------------- |
| `--name NAME`          |         | Group display name. **Repeat for several**                  |
| `-f, --from-file PATH` |         | Read display names from a file, one per line, `-` for stdin |
| `--match MODE`         | `exact` | `exact`, `prefix` or `search`                               |
| `--members`            |         | Include direct members                                      |
| `--owners`             |         | Include owners                                              |
| `--transitive`         |         | Include transitive (nested) members                         |
| `--counts`             |         | Counts only, without listing the members                    |
| `--member-limit N`     |         | Cap members or owners fetched per group                     |
| `--select FIELDS`      |         | Graph fields for the group itself                           |
| `--ignore-missing`     |         | Exit 0 when a name matches nothing                          |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure groups get --name "AWS Platform Admins"
pctl azure groups get --name "Team A" --name "Team B" --members --owners -o json
pctl azure groups get -f my-groups.txt --counts -o csv
pctl azure groups get --name platform --match search
```

### One or many

Every name is resolved **concurrently**, on one keep-alive connection pool. A single match
renders as an object, several render as an array — see
[Output and exit codes](Output-and-Exit-Codes#one-result-or-many).

At least one `--name` or `-f` is required, or you get a usage error. A name matching nothing
exits 4 unless `--ignore-missing`.

### `--counts` versus `--members`

`--counts` uses Graph's dedicated `$count` endpoint, so it does not page the whole membership
just to length it. Reach for it when you want the size of a group rather than its contents:

```bash
pctl azure groups get -f my-groups.txt --counts -o csv    # sizes of a curated list
```

### `--from-file`

One display name per line. Blank lines and `#` comments are ignored, so a curated list can
live in version control next to your infrastructure code. Values from `--name` and the file
are merged, and duplicates are dropped:

```bash
# platform-groups.txt
# reviewed quarterly
AWS Platform Admins
AWS Platform Readers
```

```bash
pctl azure groups get -f platform-groups.txt --counts
pctl azure groups list -o ndjson | jq -r .displayName | pctl azure groups get -f -
```

---

## `members`

Stream the members, or owners, of a single group.

| Flag                          | Effect                                  |
| ----------------------------- | --------------------------------------- |
| `--group NAME` **(required)** | The group, by display name              |
| `--match MODE`                | `exact` (default), `prefix` or `search` |
| `--owners`                    | List owners instead of members          |
| `--transitive`                | Include nested group members            |
| `-n, --limit N`               | Stop after N results                    |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure groups members --group "AWS Platform Admins" -o csv
pctl azure groups members --group "AWS Platform Admins" --owners
pctl azure groups members --group "AWS Platform Admins" --transitive -o ndjson
```

### members, owners, transitive

The three flags select which relationship is streamed, and they are mutually exclusive in
effect — `--owners` wins over `--transitive`:

| Flags          | Relationship        |
| -------------- | ------------------- |
| _(none)_       | `members`           |
| `--transitive` | `transitiveMembers` |
| `--owners`     | `owners`            |

`--transitive` flattens nested groups, which is what you want for "who effectively has this",
and can be much larger than the direct membership.

### Streaming

Records are written as they arrive, so `-o ndjson` and `-o csv` keep memory flat on a group
with tens of thousands of members:

```bash
pctl azure groups members --group "$BIG_GROUP" -o ndjson | wc -l
pctl azure groups members --group "$BIG_GROUP" -o ndjson | head -5   # exits 141, cleanly
```

### Ambiguity

`members` acts on exactly one group. If the name matches several, it warns on stderr and uses
the first — unlike the `eam` and write commands, which refuse. Use `--match exact` or a more
specific name when that matters.

---

## Recipes

```bash
# every group whose name starts with a prefix, as a sorted list
pctl azure groups list --starts-with aws- -o ndjson | jq -r .displayName | sort

# membership of a curated set, one CSV per group
while read -r name; do
  pctl azure groups members --group "$name" -o csv > "${name// /_}.csv"
done < platform-groups.txt

# how big is each group
pctl azure groups get -f platform-groups.txt --counts -c displayName,memberCount -o csv
```

## Related

- [Users](Azure-Users) — resolving the people a membership list refers to
- [Common options](Common-Options#matching-a-name) — the three match modes
- [Permissions](Permissions)
