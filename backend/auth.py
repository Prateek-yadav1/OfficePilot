"""Authentication and tenant identity configuration for OfficePilot."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
import os
from typing import Any


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    tenant_id: str


def _configured_users() -> dict[str, dict[str, Any]]:
    raw_users = os.getenv("OFFICEPILOT_AUTH_USERS", "").strip()
    if not raw_users:
        raise RuntimeError("OFFICEPILOT_AUTH_USERS is required.")
    try:
        configured = json.loads(raw_users)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OFFICEPILOT_AUTH_USERS must be valid JSON.") from exc
    if not isinstance(configured, dict) or not configured:
        raise RuntimeError("OFFICEPILOT_AUTH_USERS must be a non-empty JSON object.")

    users: dict[str, dict[str, Any]] = {}
    seen_user_ids: set[str] = set()
    for username, value in configured.items():
        if not isinstance(username, str) or not username.strip():
            raise RuntimeError("Authentication usernames must be non-empty strings.")
        if not isinstance(value, dict):
            raise RuntimeError("Each authentication user must be a JSON object.")
        password = value.get("password")
        user_id = value.get("user_id")
        tenant_id = value.get("tenant_id")
        if not all(
            isinstance(item, str) and item.strip()
            for item in (password, user_id, tenant_id)
        ):
            raise RuntimeError(
                "Each authentication user needs password, user_id, and tenant_id."
            )
        if len(password) < 16:
            raise RuntimeError(
                "Configured authentication passwords must be at least 16 characters."
            )
        if user_id in seen_user_ids:
            raise RuntimeError("Authentication user_id values must be unique.")
        seen_user_ids.add(user_id)
        users[username] = {
            "password": password,
            "user_id": user_id,
            "tenant_id": tenant_id,
        }
    return users


def validate_auth_configuration() -> None:
    """Fail startup when authentication is absent or malformed."""
    _configured_users()


def authenticate_basic_credentials(
    username: str,
    password: str,
) -> AuthenticatedUser | None:
    """Validate Basic credentials without logging or returning secret values."""
    try:
        users = _configured_users()
    except RuntimeError:
        raise

    candidate = users.get(username)
    expected_password = (
        candidate["password"] if candidate is not None else "invalid-credential"
    )
    valid_password = hmac.compare_digest(password, expected_password)
    if candidate is None or not valid_password:
        return None
    return AuthenticatedUser(
        user_id=candidate["user_id"],
        tenant_id=candidate["tenant_id"],
    )


def configured_tenants() -> set[str]:
    """Return tenant identifiers allowed by the local auth configuration."""
    return {
        str(value["tenant_id"])
        for value in _configured_users().values()
    }


def configured_user_tenants() -> dict[str, str]:
    """Map authenticated subject IDs to their assigned tenant IDs."""
    return {
        str(value["user_id"]): str(value["tenant_id"])
        for value in _configured_users().values()
    }
