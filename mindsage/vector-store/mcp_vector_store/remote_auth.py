"""Dependency-light bearer-token helpers for remote MindSage MCP access."""

from __future__ import annotations

import os
import secrets
from typing import Mapping, NamedTuple, Optional


MIN_REMOTE_API_KEY_LENGTH = 32
REMOTE_API_KEY_ENV_KEYS = ("VECTOR_STORE_API_KEY", "MCP_VECTOR_STORE_API_KEY")


class AuthDecision(NamedTuple):
    authorized: bool
    status_code: int
    reason_code: str


def normalize_remote_api_key(api_key: Optional[str]) -> str:
    """Return a stripped strong remote API key or raise a safe configuration error."""

    if api_key is None or not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Remote API key must be a non-empty string")

    normalized = api_key.strip()
    if len(normalized) < MIN_REMOTE_API_KEY_LENGTH:
        raise ValueError(
            f"Remote API key must be at least {MIN_REMOTE_API_KEY_LENGTH} characters"
        )
    return normalized


def resolve_remote_api_key(
    explicit_api_key: Optional[str],
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Resolve an explicit token or environment token for remote MCP/REST access."""

    if explicit_api_key is not None:
        return normalize_remote_api_key(explicit_api_key)

    source = env if env is not None else os.environ
    for key in REMOTE_API_KEY_ENV_KEYS:
        value = source.get(key)
        if value:
            return normalize_remote_api_key(value)
    return None


def extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract a Bearer token from an Authorization header."""

    if not auth_header or not isinstance(auth_header, str):
        return None
    scheme, _, token = auth_header.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def authorize_bearer_header(
    auth_header: Optional[str],
    expected_api_key: Optional[str],
) -> AuthDecision:
    """Authorize a request header against the configured API key."""

    if not expected_api_key:
        return AuthDecision(True, 200, "auth_not_configured")

    expected = normalize_remote_api_key(expected_api_key)
    provided = extract_bearer_token(auth_header)
    if provided is None:
        return AuthDecision(False, 401, "missing_bearer_token")

    if not secrets.compare_digest(provided, expected):
        return AuthDecision(False, 403, "invalid_bearer_token")

    return AuthDecision(True, 200, "authorized")


def build_auth_headers(api_key: Optional[str]) -> dict[str, str]:
    """Build HTTP headers for clients and stdio bridges calling protected servers."""

    if not api_key:
        return {}
    return {"Authorization": f"Bearer {normalize_remote_api_key(api_key)}"}
