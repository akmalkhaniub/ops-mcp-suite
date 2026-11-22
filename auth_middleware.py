"""
OAuth 2.1 Resource Server (RFC 9728) & Scope Enforcement for Ops MCP Gateway.

Implements:
  - RFC 9728 Protected Resource Metadata (`/.well-known/oauth-protected-resource`)
  - HS256 JWT Bearer verification (signature, exp, nbf, optional iss/aud, scopes)
  - API key + explicit scope-header fallback for local/CI gateway testing
  - Tool-level required scope policy map for scope-filtered `tools/list` & calls
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Iterable

from fastapi import Request

# Canonical scope catalog advertised via RFC 9728 metadata
SCOPES_SUPPORTED: tuple[str, ...] = (
    "ops.read",
    "ops.agentops.write",
    "ops.dbops.write",
    "ops.devops.write",
    "ops.github.write",
    "ops.mlops.write",
    "ops.secrets.read",
    "ops.secrets.admin",
)

# Tool -> required OAuth scope
TOOL_REQUIRED_SCOPES: dict[str, str] = {
    # AgentOps
    "create_langsmith_project": "ops.agentops.write",
    "run_eval_harness": "ops.agentops.write",
    "log_agent_trace": "ops.agentops.write",
    "get_trace_summary": "ops.read",
    "create_prompt_template": "ops.agentops.write",
    "list_prompt_versions": "ops.read",
    # DBOps
    "provision_database": "ops.dbops.write",
    "apply_migrations": "ops.dbops.write",
    "run_query": "ops.read",
    "list_tables": "ops.read",
    "clone_database": "ops.dbops.write",
    "create_read_only_user": "ops.dbops.write",
    "get_db_stats": "ops.read",
    # DevOps
    "provision_s3_bucket": "ops.devops.write",
    "generate_bedrock_credentials": "ops.devops.write",
    "manage_secrets": "ops.secrets.admin",
    "create_iam_policy": "ops.devops.write",
    "deploy_docker_container": "ops.devops.write",
    "check_service_health": "ops.read",
    # GitHub
    "list_repos": "ops.read",
    "get_repo_info": "ops.read",
    "list_pull_requests": "ops.read",
    "create_issue": "ops.github.write",
    "search_code": "ops.read",
    "get_file_contents": "ops.read",
    # MLOps
    "provision_vector_db": "ops.mlops.write",
    "trigger_fine_tuning": "ops.mlops.write",
    "list_model_registry": "ops.read",
    "promote_model": "ops.mlops.write",
    "fetch_model_metrics": "ops.read",
    "compare_models": "ops.read",
    # Secrets Manager
    "store_secret": "ops.secrets.admin",
    "get_secret": "ops.secrets.read",
    "list_secrets": "ops.secrets.read",
    "delete_secret": "ops.secrets.admin",
    "rotate_secret": "ops.secrets.admin",
    "generate_api_key": "ops.secrets.admin",
}


class AuthError(Exception):
    """Structured authentication or scope authorization error."""

    def __init__(
        self,
        status_code: int,
        error: str,
        description: str,
        required_scope: str | None = None,
    ) -> None:
        super().__init__(description)
        self.status_code = status_code
        self.error = error
        self.description = description
        self.required_scope = required_scope


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity and granted OAuth scopes."""

    subject: str
    scopes: frozenset[str]
    auth_mode: str  # "jwt" | "api_key" | "anonymous"
    scope_enforced: bool

    def has_scope(self, required_scope: str) -> bool:
        if not self.scope_enforced:
            return True
        if "*" in self.scopes or "ops.admin" in self.scopes:
            return True
        return required_scope in self.scopes


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_hs256_jwt(payload: dict, secret: str) -> str:
    """Create a signed HS256 JWT (used in tests and local CLI tooling)."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def verify_bearer_jwt(
    token: str,
    secret: str,
    expected_issuer: str | None = None,
    expected_audience: str | None = None,
) -> dict:
    """Verify an HS256 JWT Bearer token and return its claims."""
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError(401, "invalid_token", "Malformed JWT bearer token")

    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        provided_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise AuthError(401, "invalid_token", f"Unable to decode JWT: {exc}") from exc

    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError(401, "invalid_token", "JWT header and claims must be JSON objects")

    if header.get("alg") != "HS256":
        raise AuthError(401, "invalid_token", "Unsupported JWT algorithm; expected HS256")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise AuthError(401, "invalid_token", "Invalid JWT signature")

    now = time.time()
    exp = claims.get("exp")
    if exp is not None:
        try:
            exp_ts = float(exp)
        except (TypeError, ValueError) as exc:
            raise AuthError(401, "invalid_token", "Malformed JWT 'exp' claim") from exc
        if exp_ts < now:
            raise AuthError(401, "invalid_token", "Bearer token has expired")

    nbf = claims.get("nbf")
    if nbf is not None:
        try:
            nbf_ts = float(nbf)
        except (TypeError, ValueError) as exc:
            raise AuthError(401, "invalid_token", "Malformed JWT 'nbf' claim") from exc
        if nbf_ts > now:
            raise AuthError(401, "invalid_token", "Bearer token is not yet valid")

    if expected_issuer and claims.get("iss") != expected_issuer:
        raise AuthError(401, "invalid_token", "Bearer token issuer mismatch")

    if expected_audience:
        aud = claims.get("aud")
        aud_list = aud if isinstance(aud, list) else [aud]
        if expected_audience not in aud_list:
            raise AuthError(401, "invalid_token", "Bearer token audience mismatch")

    return claims


def _parse_scopes(raw: str | Iterable[str] | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    if isinstance(raw, str):
        tokens = raw.replace(",", " ").split()
        return frozenset(t.strip() for t in tokens if t.strip())
    return frozenset(str(t).strip() for t in raw if str(t).strip())


def build_protected_resource_metadata(base_url: str) -> dict:
    """Build RFC 9728 OAuth 2.0 Protected Resource Metadata document."""
    resource = base_url.rstrip("/")
    auth_servers_raw = os.environ.get(
        "OPS_OAUTH_AUTHORIZATION_SERVERS",
        "https://auth.ops-mcp.local",
    )
    auth_servers = [s.strip() for s in auth_servers_raw.split(",") if s.strip()]
    return {
        "resource": resource,
        "authorization_servers": auth_servers,
        "scopes_supported": list(SCOPES_SUPPORTED),
        "bearer_methods_supported": ["header"],
        "resource_name": "Ops MCP Gateway",
        "resource_documentation": f"{resource}/servers",
    }


def build_www_authenticate_header(
    request: Request,
    error: str | None = None,
    required_scope: str | None = None,
) -> str:
    """Format RFC 9728 / RFC 6750 WWW-Authenticate challenge header."""
    base_url = str(request.base_url).rstrip("/")
    metadata_url = f"{base_url}/.well-known/oauth-protected-resource"
    parts = [f'Bearer resource_metadata="{metadata_url}"']
    if error:
        parts.append(f'error="{error}"')
    if required_scope:
        parts.append(f'scope="{required_scope}"')
    return ", ".join(parts)


def get_required_scope(tool_name: str, is_mutating: bool = False) -> str:
    """Return the required OAuth scope for a given MCP tool name."""
    if tool_name in TOOL_REQUIRED_SCOPES:
        return TOOL_REQUIRED_SCOPES[tool_name]
    return "ops.devops.write" if is_mutating else "ops.read"


def resolve_request_principal(request: Request, require_auth_override: bool | None = None) -> Principal:
    """Authenticate an incoming HTTP request and extract granted scopes."""
    configured_key = os.environ.get("OPS_GATEWAY_API_KEY")
    jwt_secret = os.environ.get("OPS_JWT_HS256_SECRET")
    oauth_enforced = os.environ.get("OPS_OAUTH_ENFORCE", "").lower() in {"1", "true", "yes"}
    auth_required = (
        require_auth_override
        if require_auth_override is not None
        else bool(configured_key or jwt_secret or oauth_enforced)
    )

    auth_header = request.headers.get("Authorization", "")
    bearer_val = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    api_key_header = request.headers.get("X-Ops-Api-Key", "").strip()
    explicit_scopes = _parse_scopes(request.headers.get("X-Ops-Scopes"))

    # 1. Try JWT Bearer validation when OPS_JWT_HS256_SECRET is configured and a Bearer JWT is present
    if jwt_secret and bearer_val and "." in bearer_val:
        claims = verify_bearer_jwt(
            bearer_val,
            jwt_secret,
            expected_issuer=os.environ.get("OPS_OAUTH_ISSUER") or None,
            expected_audience=os.environ.get("OPS_OAUTH_AUDIENCE") or None,
        )
        jwt_scopes = _parse_scopes(claims.get("scope") or claims.get("scp"))
        return Principal(
            subject=str(claims.get("sub", "oauth-client")),
            scopes=jwt_scopes,
            auth_mode="jwt",
            scope_enforced=True,
        )

    # 2. Try static API key when OPS_GATEWAY_API_KEY is configured
    provided_key = api_key_header or bearer_val
    if configured_key:
        if provided_key and secrets.compare_digest(provided_key, configured_key):
            granted = explicit_scopes if explicit_scopes else frozenset({"*"})
            return Principal(
                subject="api-key-client",
                scopes=granted,
                auth_mode="api_key",
                scope_enforced=bool(explicit_scopes),
            )
        if auth_required:
            raise AuthError(401, "invalid_token", "Unauthorized: invalid or missing Bearer token or X-Ops-Api-Key")

    # 3. If OAuth is enforced without API key match, require valid Bearer JWT
    if auth_required:
        raise AuthError(401, "invalid_token", "Unauthorized: missing or invalid Bearer token")

    # 4. Unauthenticated local dev mode; still honor explicit X-Ops-Scopes for least-privilege filtering
    return Principal(
        subject="anonymous",
        scopes=explicit_scopes,
        auth_mode="anonymous",
        scope_enforced=bool(explicit_scopes),
    )
