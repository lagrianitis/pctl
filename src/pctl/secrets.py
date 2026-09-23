"""Load Azure credentials from AWS Secrets Manager.

The platform already keeps its Entra ID app registration in Secrets Manager (a JSON
secret with `client_id` and `client_secret`), so pctl can read from there instead of
requiring the secret in the environment. boto3 is imported lazily, so this costs
nothing unless `--secret-id` is used.
"""

from __future__ import annotations

from typing import Any

from .errors import ConfigError

DEFAULT_SECRET_REGION = "eu-central-1"

# Accept the common spellings so the same secret works across tooling.
_CLIENT_ID_KEYS = ("client_id", "clientId", "azure_client_id", "appId")
_CLIENT_SECRET_KEYS = ("client_secret", "clientSecret", "azure_client_secret", "password")
_TENANT_KEYS = ("tenant_id", "tenantId", "azure_tenant_id", "tenant")


def load_azure_secret(
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
