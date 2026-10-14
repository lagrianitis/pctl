# Troubleshooting

Real failures, what they actually mean, and the fix. Ordered roughly by how often they come
up.

**First move, always:** add `-v`. It logs which names are being resolved, how many requests
are in flight and every retry, to stderr, so it never pollutes a pipe.

```bash
pctl azure groups get --name "Team A" --members -v
```

---

## `No such option: -o`

You put a global flag in the middle:

```bash
pctl azure -o json groups list      # ✗ usage error
pctl -o json azure groups list      # ✓ before the case
pctl azure groups list -o json      # ✓ on the leaf
```

The intermediate group levels — `azure`, `groups`, `aws`, `ddb` — do not declare the global
options. Only the root and the leaf command do. Same for `-q`, `-v`, `-c` and the credential
flags.

---

## `Insufficient privileges to complete the operation`

Exit 5, with `Authorization_RequestDenied`. The credential is valid; the **permission** is
missing or not consented. Check the token rather than the portal:

```bash
pctl azure token --decode | jq -r '.roles[]' | sort
```

If the role you expect is absent there but present in the portal, **the cached token predates
the consent**. Tokens are cached for up to an hour:

```bash
pctl azure token --clear-cache
```

This is the single most common few-minutes-of-confusion with `pctl`. Granting a permission in
the portal does not retroactively change a token already on disk.

See [Permissions](Permissions#checking-what-you-actually-have) for which role each command
wants.

---

## 401 when the credentials look right

Exit 3, and **not** a consent problem. `pctl` already retries once with a freshly minted
token before reporting a 401, so if you see one the credential itself is wrong: wrong tenant,
wrong client ID, or an expired client secret.

| Status | Means                              | Fix                                  |
| ------ | ---------------------------------- | ------------------------------------ |
| 401    | The token is invalid or expired    | Check tenant, client ID, secret      |
| 403    | The token is fine, the role is not | Grant, consent, then clear the cache |

Client secrets expire. If this started working yesterday and does not today, check the
secret's expiry in the portal before anything else.

```bash
pctl azure token            # does a token come back at all?
pctl azure token --decode | jq '{aud, tid, appid, exp}'
```

---

## `2 users match ...` — exit 2, not 4

Ambiguity and absence are different failures, and `pctl` keeps them apart:

```bash
pctl azure users get --user "Example" --match prefix     # 2 match -> exit 2
pctl azure users get --user nobody@example.com           # 0 match -> exit 4
```

Exit 2 means **your input** needs narrowing. Pass the full address, an object ID, or
`--match exact`.

`--ignore-missing` does not help here, by design: it downgrades 4 to 0, never 2. Skipping a
name that matched two people would silently drop one of them.

The write commands are stricter still. `sp add-owner`, `sp remove-owner` and `sp provision`
refuse an ambiguous name outright and ask for the object ID, because a warning on stderr is
not an acceptable guard on a write.

---

## A write said it worked, but access did not change

**A 200 from the provider is not success.** Two separate cases.

### `eam add-assignment` / `remove-assignment`

These do not write an assignment. They submit an `accessPackageAssignmentRequest`, which
Entra ID then processes — through approval, policy checks and expiry rules. Exit 0 without
`--wait` means _accepted_, not _applied_.

```bash
pctl azure eam add-assignment --access-package "AWS Read" --target ann@example.com --wait
```

With `--wait` the request is polled until it settles, and anything that did not reach
`Delivered` exits 5 with the state named. `--wait-timeout` defaults to 120 seconds; a request
still pending when waiting stops is reported as pending, not assumed good, and also exits 5.

A `PartiallyDelivered` state is called out separately because the fix differs: reprocess the
existing request, do not resubmit it.

To check afterwards:

```bash
pctl azure eam get-request --request-id "$REQUEST_ID"
pctl azure eam list-assignments --access-package "AWS Read"
```

### `sp provision`

`provisionOnDemand` returns 200 and buries the verdict in a **JSON-encoded string** inside the
response. `pctl` decodes it and reports per subject:

| Outcome           | Means                                      |
| ----------------- | ------------------------------------------ |
| `applied`         | provisioned                                |
| `already-in-sync` | source and target already matched, a no-op |
| `failed`          | nothing was provisioned                    |

A subject that is **out of scope or unassigned** comes back as a skip, which counts as
`failed` — because nothing was provisioned. Any result the code has never seen also counts as
failed, rather than being optimistically read as success. Any `failed` row exits 5.

See [Service principals](Azure-Service-Principals#a-200-does-not-mean-it-worked).

---

## `Could not find a property named 'target'`

A Graph 400 of this shape means an `$expand` or `$select` names a relationship the resource
does not have:

```
Parsing OData Select and Expand failed: Could not find a property named 'target' on type
'microsoft.graph.accessPackageAssignmentRequest'
```

This was a real bug, fixed in v0.2.0. An assignment **request** has `accessPackage`,
`assignment` and `requestor` — no `target`; an assignment does have `target`. It broke
`eam get-request` and every `--wait`, since waiting polls the request.

If you see it now, it is from a hand-built `azure raw` call. Check the resource's
relationships before expanding them; the error message names the exact type, which is the
fastest way to look it up.

---

## `pctl ddb scan` does nothing useful

At the root, `ddb` is an alias for the **case** `aws`, so `pctl ddb scan` expands to
`pctl aws scan` and fails — `scan` belongs to `ddb`, not to `aws`:

```bash
pctl ddb scan        # ✗
pctl aws ddb scan    # ✓
```

The root aliases are `az` and `graph` for `azure`, and `dynamodb` and `ddb` for `aws`. They
rename a case, they do not skip a level. See
[Finding a command](Finding-Commands#aliases).

---

## `No AWS region configured`

Exit 2. The boto3 chain found credentials but no region:

```bash
pctl aws ddb tables --region eu-central-1
export AWS_REGION=eu-central-1
```

Local DynamoDB needs one too, even though it ignores it.

---

## `zsh: illegal modifier` or a mangled expression

The shell ate your argument. Three separate traps:

```bash
# ! expands inside DOUBLE quotes in zsh
pctl azure raw --path users --param '$filter=startswith(displayName,'"'"'a'"'"')'

# $ expands inside double quotes everywhere
pctl azure raw --path users --param '$select=id,displayName'   # single quotes ✓
pctl azure raw --path users --param "$select=id,displayName"   # ✗ empty

# { } and : are fine, but the JSON needs single quotes to survive
pctl aws ddb get --table t --key '{"pk":"tenant#42"}'
```

**Single-quote anything containing `$`, `!`, `{` or `#`.** That covers every OData parameter,
every DynamoDB expression, and every `--key`/`--values` JSON payload.

---

## `expected KEY=VALUE`

`azure raw --param` takes one `key=value` per flag, repeated:

```bash
pctl azure raw --path users --param '$select=id,displayName' --param '$top=5'
```

Not `--param '$select id'`, and not several parameters in one flag.

---

## `still has N assignment(s)` on `delete-package`

Graph will not delete an access package while **any** assignment exists, whatever its state.
`pctl` checks first and tells you the breakdown, instead of passing back a bare 400:

```bash
pctl azure eam list-assignments --access-package "Retired Access"
pctl azure eam remove-assignment --access-package "Retired Access" --target ann@example.com --wait
pctl azure eam delete-package --access-package "Retired Access"
```

`--force` skips the pre-check and lets Graph decide, which only helps if you believe the check
is being over-cautious.

Related refusals from the same command:

| Message                                  | Means                                                  |
| ---------------------------------------- | ------------------------------------------------------ |
| `No access package is named exactly ...` | `delete-package` has no substring fallback, on purpose |
| `N access packages are named ...`        | Pass the object ID of the one to delete                |
| Aborted with no output                   | You declined the prompt. Exit 1, not 0                 |

In a pipeline stdin is not a terminal, so `--yes` is required. See
[Entitlement management](Azure-Entitlement-Management#delete-package).

---

## `This application has N synchronization jobs`

`sp provision` refuses to guess. A tenant with both an inbound and an outbound job would
otherwise provision in whichever direction answered first. The message lists the IDs:

```bash
pctl azure sp provision --app "$APP" --group "Team A" --job "$JOB" --rule "$RULE"
```

`This application has no synchronization job` means provisioning was never configured for it —
a portal task, not a CLI one.

Rule IDs are not plain GUIDs; a versioned rule looks like `<guid>#V2`. Single-quote it, or the
shell treats `#V2` as a comment.

---

## `This access package has N assignment policies`

Same principle: an `adminAdd` request must name a policy, and policies carry different
approval and expiry rules. Granting under the wrong one is a silent mistake, so it asks:

```bash
pctl azure eam get-package --access-package "AWS Read" -o json | jq '.accessPackageAssignmentPolicies'
pctl azure eam add-assignment --access-package "AWS Read" --target ann@example.com --policy "Direct"
```

With exactly one policy you never see this.

---

## A scan is slow, or throttling

| Symptom                             | Cause and fix                                                                          |
| ----------------------------------- | -------------------------------------------------------------------------------------- |
| Slow with default settings          | Raise `--segments`. Default is `min(8, CPU count)`                                     |
| Throttled, or the table slows down  | Lower `--segments`. You are outrunning provisioned capacity                            |
| `-n 5` takes as long as a full scan | It should not — `--limit` forces one segment. Check you did not also pass `--segments` |
| Memory grows                        | `-o table` buffers every row to align columns. Use `-o ndjson`                         |

`--filter` does not make a scan cheaper: DynamoDB reads the item, then discards it. Only
`--key` on a [`query`](AWS-DynamoDB#query) avoids the read.

Watch what is actually happening with `-v`, which logs each page and the segment count.

---

## Output is empty but the exit code is 0

Almost always a `list` with a filter that matched nothing — an empty array is a successful
result, not a miss. Only the `get`-style commands, which are asked for a _specific_ thing,
exit 4.

Check the filter in isolation:

```bash
pctl azure groups list --starts-with aws- --count-only
pctl azure eam list-packages --contains aws      # local substring, slower but forgiving
```

On `eam`, remember `--name` is an exact server-side match. `--starts-with` and `--contains`
are what you want when you are not sure of the full name.

---

## A traceback instead of an error message

Every expected failure is a clean `Error: ...` on stderr with a documented exit code. A
traceback is a bug — please
[open an issue](https://github.com/lagrianitis/pctl/issues) with the command, the `-v` output
and the version:

```bash
pctl --version
```

A broken pipe is **not** a bug: `| head` exits 141 quietly, by design.

---

## Still stuck

```bash
pctl commands | grep -i <word>    # is there a command for this?
pctl tree                         # what is the shape of it
pctl azure eam get-package -h     # what does this one take
pctl azure raw --path <path> -v   # go under the CLI entirely
```

`azure raw` gets auth, retries and pagination for free, so it is a fair way to check whether a
problem is in `pctl` or in Graph. If `raw` fails the same way, the problem is upstream.

## Related

- [Permissions](Permissions) — what to grant, and how to verify it
- [Output and exit codes](Output-and-Exit-Codes) — the full exit code table
- [Common options](Common-Options) — `--match`, `--wait`, `--ignore-missing`
- [Finding a command](Finding-Commands)
