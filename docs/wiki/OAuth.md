# `pctl oauth`

Fetch a JWT from any OAuth 2.0 provider: Auth0, Okta, Keycloak and the rest. Two commands
sit directly under `oauth`, with no service in between, because there is nothing to list or
get, only a token to fetch.

| Command | For      | Flow                                  |
| ------- | -------- | ------------------------------------- |
| `token` | machines | client credentials                    |
| `login` | people   | authorization code with PKCE, browser |

`auth` and `auth0` are aliases for `oauth`, so `pctl auth0 token` works.

---

## Settings

Every setting is a flag **and** an environment variable. The flag wins when both are set.

| Flag               | Environment            | Notes                                                       |
| ------------------ | ---------------------- | ----------------------------------------------------------- |
| `--issuer URL`     | `OAUTH_ISSUER`         | Provider base URL. Endpoints are discovered from it         |
| `--token-url URL`  | `OAUTH_TOKEN_URL`      | Token endpoint. Skips discovery                             |
| `--client-id ID`   | `OAUTH_CLIENT_ID`      | Always required                                             |
| `--client-secret`  | `OAUTH_CLIENT_SECRET`  | Required for `token`, optional for `login`                  |
| `--audience API`   | `OAUTH_AUDIENCE`       | The API the token is for                                    |
| `--scope SCOPES`   | `OAUTH_SCOPE`          | Space-separated. `login` defaults to `openid profile email` |
| `--secret-id NAME` | `PCTL_OAUTH_SECRET_ID` | Reads `client_id`/`client_secret` from AWS Secrets Manager  |
| `--secret-region`  | `PCTL_SECRET_REGION`   | Region holding that secret. Default `eu-central-1`          |

Name the provider with `--issuer`, or give `--token-url`. With only an issuer, `pctl` reads
`<issuer>/.well-known/openid-configuration` once to find the endpoints; naming the URLs
yourself costs no extra request.

### The client secret as a flag

`--client-secret` exists so every setting can be given on the command line, and it is the
only secret flag in `pctl`. A flag lands in shell history and in the process list, so
prefer the variable or `--secret-id`:

```bash
export OAUTH_CLIENT_SECRET=...
pctl oauth token --issuer https://idp.example.com --client-id my-client
```

The value is never printed, logged or written to the cache.

---

## `token`

Fetch an access token with the client credentials grant. No browser, no user: the client id
and secret are exchanged for a token.

**Needs:** `--client-id`, a secret, and a provider.

| Flag               | Environment           | Effect                                                   |
| ------------------ | --------------------- | -------------------------------------------------------- |
| `--raw`            |                       | Print only the access token, unmasked                    |
| `--decode`         |                       | Show the token's claims, without verifying the signature |
| `--no-token-cache` | `PCTL_NO_TOKEN_CACHE` | Do not read or write the on-disk token cache             |

Plus the [global options](Common-Options).

```bash
pctl oauth token --issuer https://idp.example.com \
    --client-id my-client --audience https://api.example.com
pctl oauth token --decode -o json | jq .claims
```

### The token is masked by default

Like [`azure token`](Azure-Token-and-Raw#the-token-is-masked-by-default), the token is
masked unless you ask for it. `--raw` prints it and nothing else, which is what a header
needs:

```bash
curl -H "Authorization: Bearer $(pctl oauth token --raw)" https://api.example.com/things
```

Treat that output as a secret.

### Caching

A machine token is cached at `${XDG_CACHE_HOME:-~/.cache}/pctl/tokens`, mode `0600` inside
a `0700` directory, until it expires. Three commands in a row make one request.

The cache is keyed on the provider, the client id, the audience and the scope, and never on
the secret. A token for one audience is not reused for another. A response with no
`expires_in` is not reused at all.

---

## `login`

Log in through the browser and fetch a user token, using the authorization code flow with
PKCE. The login page is opened with a hashed challenge; the code it returns is useless to
anyone who intercepts it, because only this process holds the verifier.

**Needs:** `--client-id`, a provider, and `--redirect-uri`. A secret is optional: a public
client needs none.

| Flag              | Environment           | Effect                                                   |
| ----------------- | --------------------- | -------------------------------------------------------- |
| `--authorize-url` | `OAUTH_AUTHORIZE_URL` | Authorization endpoint. Skips discovery                  |
| `--redirect-uri`  | `OAUTH_REDIRECT_URI`  | Redirect registered on the client                        |
| `--login-timeout` | `OAUTH_LOGIN_TIMEOUT` | Seconds to wait for the browser. Default 300             |
| `--raw`           |                       | Print only the access token, unmasked                    |
| `--decode`        |                       | Show the token's claims, without verifying the signature |

```bash
pctl oauth login --issuer https://idp.example.com --client-id my-client \
    --redirect-uri http://127.0.0.1:8765/callback
```

### Two ways back from the browser

**A loopback redirect.** With `--redirect-uri http://127.0.0.1:PORT/path` or `localhost`,
`pctl` listens on that port itself, opens the browser, and reads the code when the browser
arrives. Nothing to copy. The port must be given, and the same address must be registered
on the client.

**Any other redirect.** If the client's registered redirect is a hosted page, `pctl` cannot
listen for it. The browser lands on that page, which may show an error: ignore it, copy the
whole address from the address bar, and paste it at the prompt. Pasting just the `code`
value works too.

If no browser opens, the login address is printed to stderr so you can open it yourself.

### What is refused

| Situation                                                                            | Result                            |
| ------------------------------------------------------------------------------------ | --------------------------------- |
| The redirect's `state` does not match this login                                     | Exit 3, nothing is exchanged      |
| A loopback redirect arrives with no `state`                                          | Exit 3, nothing is exchanged      |
| The provider sends back an error (user said no)                                      | Exit 3 with the provider's reason |
| The redirect carries no code                                                         | Exit 3                            |
| Nobody comes back within `--login-timeout`                                           | Exit 3                            |
| The provider rejects the code exchange                                               | Exit 3 with the provider's reason |
| No redirect, a loopback redirect with no port, a busy port, or no authorize endpoint | Exit 2, before the browser opens  |

### Nothing is kept

A user token is never cached, and no refresh token is kept. Each `login` starts a fresh
login.

---

## Exit codes

| Code | When                                                                         |
| ---- | ---------------------------------------------------------------------------- |
| 0    | A token was returned                                                         |
| 2    | Missing or unusable configuration, found before anything was sent            |
| 3    | The provider rejected the credentials, refused the login, or was unreachable |

See [Output and exit codes](Output-and-Exit-Codes) for the full table.

## Related

- [Common options](Common-Options) — `-o`, `-q`, `-v` and the other global flags
- [Output and exit codes](Output-and-Exit-Codes)
- [Azure token and raw](Azure-Token-and-Raw) — the same masking and caching for Microsoft Graph
- [Troubleshooting](Troubleshooting)
