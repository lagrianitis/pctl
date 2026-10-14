# `pctl azure users`

Resolve a person to their directory object from whatever you happen to know about them.
Read-only.

**Permission:** `User.Read.All`.

---

## `get`

| Flag                   | Default | Effect                                                           |
| ---------------------- | ------- | ---------------------------------------------------------------- |
| `--user VALUE`         |         | Email address, display name or object ID. **Repeat for several** |
| `-f, --from-file PATH` |         | One identifier per line, `-` for stdin                           |
| `--match MODE`         | `exact` | How to match a _display name_: `exact`, `prefix` or `search`     |
| `--select FIELDS`      |         | Comma-separated Graph fields                                     |
| `--ignore-missing`     |         | Exit 0 when an identifier matches nothing                        |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure users get --user ann@company.com
pctl azure users get --user "Ann Example" -o json
pctl azure users get --user e6901838-637f-4bc7-b843-a8a7725a4872
pctl azure users get --user ann@company.com --user bob@company.com -o ndjson
pctl azure users get -f people.txt --ignore-missing
```

## Three identifier forms, no flag to choose

Which form you passed is **inferred**, because it is obvious from the value:

| You pass                | `pctl` does                                        |
| ----------------------- | -------------------------------------------------- |
| A GUID                  | Addresses `/users/{id}` directly — no query at all |
| Anything containing `@` | Matches `userPrincipalName` **or** `mail`          |
| Anything else           | Matches `displayName`, using `--match`             |

There is no `--by-email` or `--by-id`, because a canonical GUID is never a display name and an
Entra ID display name never contains an `@`.

### Why an address is matched against two fields

They routinely differ. A tenant may have `lef@company.onmicrosoft.com` as the UPN while mail
is `lef@company.com`, and whoever is typing knows one of them, not both. So:

```
$filter=userPrincipalName eq 'ann@company.com' or mail eq 'ann@company.com'
```

Always an exact comparison — there is no sensible prefix match on an address.

## An ambiguous name is refused, not guessed

Two people can share a display name, and every caller of this is about to act on the answer:

```
$ pctl azure users get --user "Example" --match prefix
Error: 2 users match 'Example'. Use the email address or the object ID, so the wrong one
cannot be chosen.
```

That is **exit 2**, a usage error — your input needs fixing. A name matching _nothing_ is
exit 4. `--ignore-missing` covers the second case and deliberately not the first: skipping a
name that matched two people would drop one of them silently. See
[Output and exit codes](Output-and-Exit-Codes#the-distinctions-that-matter).

## Several at once

Resolved concurrently, and one bad identifier does not block the others:

```bash
pctl azure users get --user ann@company.com --user nobody@company.com -o ndjson
# Ann is returned on stdout, the miss is reported on stderr, exit 4
```

Add `--ignore-missing` to make that exit 0 while still printing the warning.

## Where else this resolution is used

The same logic backs every command that names a person, so an address matched one way in one
command cannot be matched differently in another:

- [`sp add-owner` / `remove-owner`](Azure-Service-Principals#add-owner) — `--owner`
- [`eam add-assignment` / `remove-assignment`](Azure-Entitlement-Management#add-assignment) — `--target`
- [`sp provision`](Azure-Service-Principals#provision) — `--user`

The difference is strictness: `users get` will warn and continue across a batch, whereas the
writes refuse an ambiguous name outright, because they are about to grant or revoke access.

## Recipes

```bash
# object ID for a list of addresses, as TSV
pctl -o ndjson azure users get -f people.txt --ignore-missing \
  | jq -r '[.userPrincipalName, .id] | @tsv'

# does this person exist, exit code only
pctl azure users get --user someone@company.com -q > /dev/null && echo yes || echo no

# resolve the members of a group to full user records
pctl azure groups members --group "$GROUP" -o ndjson \
  | jq -r .userPrincipalName \
  | pctl azure users get -f - --ignore-missing -o csv
```

## Related

- [Groups](Azure-Groups) — `members` gives you the people, this gives you their details
- [Common options](Common-Options#matching-a-name)
- [Permissions](Permissions)
