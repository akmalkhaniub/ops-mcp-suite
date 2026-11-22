import logging
import os
import sys
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agentops_mcp
import dbops_mcp
import devops_mcp
import github_mcp
import mlops_mcp
import secrets_mcp
from auth_middleware import TOOL_REQUIRED_SCOPES, create_hs256_jwt
from gateway import _extract_mcp_tools, app
from secret_scrubber import SecretRedactingFilter, redact_payload, redact_secrets


def test_all_six_servers_expose_tool_annotations():
    modules = {
        "agentops": agentops_mcp,
        "dbops": dbops_mcp,
        "devops": devops_mcp,
        "github": github_mcp,
        "mlops": mlops_mcp,
        "secrets": secrets_mcp,
    }
    total_tools = 0
    for server_id, mod in modules.items():
        tools = _extract_mcp_tools(mod.mcp)
        assert tools, f"{server_id} registered no tools"
        for name, tool in tools.items():
            total_tools += 1
            ann = getattr(tool, "annotations", None)
            assert ann is not None, f"{server_id}.{name} is missing ToolAnnotations"
            assert ann.readOnlyHint is not None
            assert ann.destructiveHint is not None
            assert name in TOOL_REQUIRED_SCOPES, f"{name} missing from TOOL_REQUIRED_SCOPES"

    assert total_tools == 37


def test_rfc9728_protected_resource_metadata():
    client = TestClient(app)
    resp = client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resource"] == "http://testserver"
    assert isinstance(data["authorization_servers"], list) and data["authorization_servers"]
    assert "ops.read" in data["scopes_supported"]
    assert "ops.secrets.admin" in data["scopes_supported"]
    assert data["bearer_methods_supported"] == ["header"]


def test_oauth_jwt_challenge_scope_filtering_and_enforcement(monkeypatch, tmp_path):
    secret = "unit-test-hs256-secret-key-2026"
    monkeypatch.setenv("OPS_JWT_HS256_SECRET", secret)
    monkeypatch.delenv("OPS_GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("OPS_DB_WORKSPACE_ROOT", str(tmp_path))

    client = TestClient(app)

    # 1. Missing token -> 401 with RFC 9728 WWW-Authenticate header
    unauth = client.post("/dbops/call/list_tables", json={"db_path": "demo.db"})
    assert unauth.status_code == 401
    www_auth = unauth.headers.get("www-authenticate", "")
    assert 'resource_metadata="http://testserver/.well-known/oauth-protected-resource"' in www_auth

    # 2. Expired token -> 401
    expired_jwt = create_hs256_jwt(
        {"sub": "agent-1", "scope": "ops.read", "exp": time.time() - 60},
        secret,
    )
    exp_resp = client.post(
        "/dbops/call/list_tables",
        headers={"Authorization": f"Bearer {expired_jwt}"},
        json={"db_path": "demo.db"},
    )
    assert exp_resp.status_code == 401

    # 3. Valid read-only JWT -> filters tools/list and blocks write tool with 403 insufficient_scope
    read_jwt = create_hs256_jwt(
        {"sub": "agent-readonly", "scope": "ops.read", "exp": time.time() + 300},
        secret,
    )
    tools_resp = client.get("/dbops/tools", headers={"Authorization": f"Bearer {read_jwt}"})
    assert tools_resp.status_code == 200
    listed_names = {t["name"] for t in tools_resp.json()["tools"]}
    assert {"run_query", "list_tables", "get_db_stats"}.issubset(listed_names)
    assert "apply_migrations" not in listed_names
    assert "clone_database" not in listed_names
    # Verify annotations are surfaced in REST discovery
    run_q = next(t for t in tools_resp.json()["tools"] if t["name"] == "run_query")
    assert run_q["annotations"]["readOnlyHint"] is True
    assert run_q["required_scope"] == "ops.read"

    denied = client.post(
        "/dbops/call/apply_migrations",
        headers={"Authorization": f"Bearer {read_jwt}"},
        json={"db_url": "sqlite:///demo.db", "dry_run": True},
    )
    assert denied.status_code == 403
    assert denied.json()["required_scope"] == "ops.dbops.write"
    assert 'error="insufficient_scope"' in denied.headers.get("www-authenticate", "")
    assert 'scope="ops.dbops.write"' in denied.headers.get("www-authenticate", "")

    # 4. Write-scoped JWT -> succeeds
    write_jwt = create_hs256_jwt(
        {"sub": "agent-migrator", "scope": "ops.read ops.dbops.write", "exp": time.time() + 300},
        secret,
    )
    allowed = client.post(
        "/dbops/call/apply_migrations",
        headers={"Authorization": f"Bearer {write_jwt}"},
        json={"db_url": "sqlite:///demo.db", "dry_run": True},
    )
    assert allowed.status_code == 200


def test_secret_scrubber_redacts_credentials_and_logs(monkeypatch):
    fernet_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("VAULT_MASTER_KEY", fernet_key)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_1234567890abcdefghijklmnopqr")

    raw = (
        f"Failed with VAULT_MASTER_KEY={fernet_key} "
        "and header Authorization: Bearer super_secret_token_999999 "
        "using AWS AKIAIOSFODNN7EXAMPLE and ghp_1234567890abcdefghijklmnopqr"
    )
    cleaned = redact_secrets(raw)
    assert fernet_key not in cleaned
    assert "ghp_1234567890abcdefghijklmnopqr" not in cleaned
    assert "AKIAIOSFODNN7EXAMPLE" not in cleaned
    assert "super_secret_token_999999" not in cleaned
    assert "[REDACTED" in cleaned

    nested = redact_payload({"error": "sk_live_abcdefghijklmnopqrst", "items": ["ghp_abcdefghijklmnopqrstuvwx"]})
    assert "sk_live_" not in nested["error"]
    assert "ghp_" not in nested["items"][0]

    record = logging.LogRecord(
        name="secrets_mcp",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Error using key %s",
        args=(fernet_key,),
        exc_info=None,
    )
    SecretRedactingFilter().filter(record)
    assert fernet_key not in record.getMessage()

    # Raw JWT and nested dict log args are also redacted cleanly
    sample_jwt = create_hs256_jwt({"sub": "alice", "scope": "ops.read"}, "secret-key-123456")
    assert sample_jwt not in redact_secrets(f"leaked token={sample_jwt}")
    nested_rec = logging.LogRecord(
        name="secrets_mcp",
        level=logging.ERROR,
        pathname=__file__,
        lineno=2,
        msg="Nested payload %s",
        args=({"token": sample_jwt},),
        exc_info=None,
    )
    SecretRedactingFilter().filter(nested_rec)
    assert sample_jwt not in nested_rec.getMessage()


def test_malformed_jwt_claims_return_401_instead_of_500(monkeypatch):
    import base64
    import hashlib
    import hmac
    import json

    secret = "unit-test-hs256-secret-key-2026"
    monkeypatch.setenv("OPS_JWT_HS256_SECRET", secret)
    client = TestClient(app)

    bad_exp_jwt = create_hs256_jwt({"sub": "agent-1", "exp": "not-a-number"}, secret)
    resp = client.get("/dbops/tools", headers={"Authorization": f"Bearer {bad_exp_jwt}"})
    assert resp.status_code == 401

    # Valid HS256 signature over non-object JSON payload (`[]`) must return 401, not 500
    hdr = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode("ascii")
    pld = base64.urlsafe_b64encode(json.dumps([]).encode()).rstrip(b"=").decode("ascii")
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), f"{hdr}.{pld}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")
    non_dict_jwt = f"{hdr}.{pld}.{sig}"
    resp2 = client.get("/dbops/tools", headers={"Authorization": f"Bearer {non_dict_jwt}"})
    assert resp2.status_code == 401
