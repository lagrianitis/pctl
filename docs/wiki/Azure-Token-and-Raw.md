# `pctl azure token` and `raw`

Two case-level commands that sit directly under `azure` rather than under a service: one for
the credential, one for anything this CLI does not cover yet.

---

## `token`

Acquire an access token for Microsoft Graph, using the cache.

**Permission:** none beyond a working credential. This is the command to reach for when you
need to know whether the credential itself is the problem.

| Flag            | Effect                                                   |
| --------------- | -------------------------------------------------------- |
| `--raw`         | Print only the bearer token, unmasked                    |
| `--decode`      | Show the token's claims, without verifying the signature |
| `--clear-cache` | Delete all cached tokens and exit                        |

Plus the [credential and global options](Common-Options).

```bash
pctl azure token                    # masked, with the expiry
pctl azure token --decode           # inspect the claims
pctl azure token --clear-cache      # drop every cached token
```

### The token is masked by default

A bearer token in a terminal ends up in scrollback, in CI logs and in anyone's screen
recording. `--raw` is the explicit opt-in:

```bash
curl -H "Authorization: Bearer $(pctl azure token --raw)" \
     https://graph.microsoft.com/v1.0/me
```

Treat that output as a secret. It is valid for up to an hour.

### `--decode` is the fastest permission check

It prints the claims, including the `roles` array — which is the _authoritative_ list of what
the token can do, as opposed to what the portal says has been consented:

```bash
pctl azure token --decode | jq -r '.roles[]' | sort
```

If a role you granted is missing here, the cached token predates the consent. See
[the caching section](#caching) below and [Permissions](Permissions#checking-what-you-actually-have).

> `--decode` does not verify the signature. It is for inspection, never for an authorisation
> decision.

### Caching

Tokens are cached on disk at `${XDG_CACHE_HOME:-~/.cache}/pctl/tokens`, mode `0600` inside a
`0700` directory. That is why three commands in a row authenticate once.

The cache is the cause of the most common confusion in this CLI: **a token issued before a
permission was consented does not carry the new role**, and it lives for up to an hour. After
changing consent:

```bash
pctl azure token --clear-cache
```

Disable caching entirely with `--no-token-cache` or `PCTL_NO_TOKEN_CACHE=1`.

---

## `raw`

Call any Graph path, with authentication, retries and pagination handled.

**Permission:** whatever the path you call requires. `raw` adds nothing and removes nothing.

| Flag                         | Default  | Effect                                |
| ---------------------------- | -------- | ------------------------------------- |
| `--path PATH` **(required)** |          | Path relative to the API version root |
| `--param KEY=VALUE`          |          | A query parameter. Repeat for several |
| `--paginate / --no-paginate` | paginate | Follow `@odata.nextLink`              |
| `-n, --limit N`              |          | Stop after N items                    |

Plus the [credential, column and global options](Common-Options).

```bash
pctl azure raw --path users --param '$select=id,displayName' -n 10
pctl azure raw --path organization --no-paginate
pctl azure raw --path "groups/$GROUP_ID/transitiveMembers" -o ndjson
```

### What you get for free

`raw` is not a bare HTTP client. It reuses the same transport as every other command, so you
get token acquisition and caching, retry with backoff on 429 and 5xx honouring `Retry-After`,
`@odata.nextLink` pagination, and the same four output formats and exit codes.

### `--paginate` versus `--no-paginate`

With pagination on — the default — items are streamed through the renderer one at a time, so
`-o ndjson` works on a collection of any size and `-n` stops early.

With `--no-paginate`, the raw response document is printed as-is, pretty-printed. Use it for
endpoints that return a single object rather than a collection, like `organization`, where a
`value` array does not exist.

### Quoting `$` parameters

OData parameters start with `$`, which your shell will try to expand. Single-quote them:

```bash
pctl azure raw --path users --param '$select=id,displayName'    # right
pctl azure raw --path users --param "$select=id,displayName"    # $select expands to nothing
```

A `--param` without an `=` is rejected before any request is made:

```
Error: expected KEY=VALUE, got 'broken'
```

### When to use it

When the thing you need is not modelled yet. If you find yourself using `raw` for the same
task twice, that is the signal for a real command — the services in this CLI each started
that way.

---

## Related

- [Permissions](Permissions) — including the 401 versus 403 distinction
- [Troubleshooting](Troubleshooting) — the cached-token trap in full
- [Output and exit codes](Output-and-Exit-Codes)
