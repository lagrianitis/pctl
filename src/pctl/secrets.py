"""Read and write client credentials in AWS Secrets Manager.

The platform already keeps its Entra ID app registration in Secrets Manager (a JSON
secret with `client_id` and `client_secret`), so pctl can read from there instead of
requiring the secret in the environment. Any OAuth client stored the same way works too,
which is why the loader is not named for one provider. `SecretObject` is the other
direction: it adds keys to a secret, which is where a newly created client secret goes
so that its value, shown by Graph only once, is not lost. boto3 is imported lazily, so
this costs nothing unless a secret is actually used.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ConfigError, UpstreamError

DEFAULT_SECRET_REGION = "eu-central-1"

# Accept the common spellings so the same secret works across tooling.
_CLIENT_ID_KEYS = ("client_id", "clientId", "azure_client_id", "appId")
_CLIENT_SECRET_KEYS = ("client_secret", "clientSecret", "azure_client_secret", "password")
_TENANT_KEYS = ("tenant_id", "tenantId", "azure_tenant_id", "tenant")


def load_client_secret(
    secret_id: str,
    *,
    region: str | None = None,
    profile: str | None = None,
) -> dict[str, str]:
    """Fetch a JSON secret and normalise it to `client_id`/`client_secret`/`tenant_id`."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    region = region or DEFAULT_SECRET_REGION
    try:
        session = boto3.session.Session(profile_name=profile or None, region_name=region)
        response = session.client("secretsmanager").get_secret_value(SecretId=secret_id)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        message = exc.response.get("Error", {}).get("Message", str(exc))
        if code == "ResourceNotFoundException":
            raise ConfigError(f"Secret '{secret_id}' not found in {region}.") from exc
        if code in {"AccessDeniedException", "UnrecognizedClientException"}:
            raise ConfigError(
                f"Not allowed to read secret '{secret_id}' in {region}: {message}"
            ) from exc
        raise ConfigError(f"Could not read secret '{secret_id}': {message}") from exc
    except BotoCoreError as exc:
        raise ConfigError(f"Could not read secret '{secret_id}': {exc}") from exc

    payload = _parse(response, secret_id)
    resolved = {
        "client_id": _pick(payload, _CLIENT_ID_KEYS),
        "client_secret": _pick(payload, _CLIENT_SECRET_KEYS),
        "tenant_id": _pick(payload, _TENANT_KEYS),
    }
    if not resolved["client_secret"]:
        raise ConfigError(
            f"Secret '{secret_id}' has no client_secret field. "
            f"Expected JSON with keys: {', '.join(_CLIENT_SECRET_KEYS)}."
        )
    return {key: value for key, value in resolved.items() if value}


def _parse(response: dict[str, Any], secret_id: str) -> dict[str, Any]:
    import orjson

    raw = response.get("SecretString")
    if raw is None:
        binary = response.get("SecretBinary")
        if binary is None:
            raise ConfigError(f"Secret '{secret_id}' is empty.")
        raw = bytes(binary).decode("utf-8", errors="replace")
    try:
        payload = orjson.loads(raw)
    except orjson.JSONDecodeError as exc:
        raise ConfigError(
            f"Secret '{secret_id}' is not JSON; expected an object with client_id "
            "and client_secret."
        ) from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"Secret '{secret_id}' must be a JSON object.")
    return payload


def _pick(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@dataclass(slots=True, frozen=True)
class SecretObject:
    """A Secrets Manager secret whose value is a JSON object, which pctl adds keys to.

    Writing is read-modify-write, because Secrets Manager replaces a secret's whole value.
    `check` runs before anything irreversible, so a secret that cannot take the keys is
    found out about while there is still nothing to lose. `add` reads the secret again just
    before it writes, so a key someone else added in between is kept rather than erased.
    Neither ever puts a value in a message.
    """

    secret_id: str
    region: str | None = None
    profile: str | None = None

    def check(self, keys: Iterable[str], *, overwrite: bool) -> None:
        """Raise unless the secret exists, is live, is a JSON object and has room for `keys`."""
        client = self._client()
        self._ensure_live(client)
        self._ensure_free(self._read(client), keys, overwrite)

    def add(self, entries: Mapping[str, str], *, overwrite: bool) -> None:
        """Merge `entries` into the secret, keeping every other key it holds."""
        client = self._client()
        current = self._read(client)
        self._ensure_free(current, entries, overwrite)
        self._put(client, {**current, **entries})

    def _client(self) -> Any:
        import boto3

        region = self.region or DEFAULT_SECRET_REGION
        session = boto3.session.Session(profile_name=self.profile or None, region_name=region)
        return session.client("secretsmanager")

    def _ensure_live(self, client: Any) -> None:
        """Refuse a secret scheduled for deletion, which would reject the write later."""
        description = self._call(client.describe_secret, SecretId=self.secret_id)
        if description.get("DeletedDate"):
            raise ConfigError(f"Secret '{self.secret_id}' is scheduled for deletion.")

    def _read(self, client: Any) -> dict[str, Any]:
        response = self._call(client.get_secret_value, SecretId=self.secret_id)
        return _parse(response, self.secret_id)

    def _ensure_free(
        self, current: Mapping[str, Any], keys: Iterable[str], overwrite: bool
    ) -> None:
        clash = sorted(key for key in keys if key in current)
        if clash and not overwrite:
            raise ConfigError(
                f"Secret '{self.secret_id}' already has {', '.join(clash)}. "
                "Use --overwrite to replace them."
            )

    def _put(self, client: Any, value: Mapping[str, Any]) -> None:
        import orjson
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            client.put_secret_value(
                SecretId=self.secret_id, SecretString=orjson.dumps(value).decode()
            )
        except (ClientError, BotoCoreError) as exc:
            raise UpstreamError(
                f"Could not write secret '{self.secret_id}': {_reason(exc)}"
            ) from exc

    def _call(self, method: Any, **kwargs: Any) -> dict[str, Any]:
        """Call Secrets Manager, turning its failures into the errors a caller expects."""
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return dict(method(**kwargs))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ResourceNotFoundException":
                raise ConfigError(f"Secret '{self.secret_id}' was not found.") from exc
            raise ConfigError(f"Cannot use secret '{self.secret_id}': {_reason(exc)}") from exc
        except BotoCoreError as exc:
            raise ConfigError(f"Cannot use secret '{self.secret_id}': {exc}") from exc


def _reason(exc: Exception) -> str:
    """The provider's own message for a failure, which never contains a secret's value."""
    response = getattr(exc, "response", None) or {}
    return str(response.get("Error", {}).get("Message") or exc)
