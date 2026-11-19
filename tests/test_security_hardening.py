import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import dbops_mcp
from gateway import app
from securityops_mcp import SecurityOpsMCP


def test_dbops_readonly_sql_blocks_stacked_and_nospace_injection():
    assert dbops_mcp._is_read_only_query("SELECT id, name FROM users LIMIT 10") is True
    assert dbops_mcp._is_read_only_query("SELECT 1;DROP TABLE users") is False
    assert dbops_mcp._is_read_only_query("WITH x AS (SELECT 1) DELETE FROM users") is False


def test_dbops_workspace_root_confinement(tmp_path, monkeypatch):
    monkeypatch.setenv("OPS_DB_WORKSPACE_ROOT", str(tmp_path))
    safe_db = tmp_path / "app.db"
    safe_db.write_bytes(b"")
    assert dbops_mcp._resolve_db_path(str(safe_db)) == safe_db.resolve()

    with pytest.raises(ValueError, match="Path traversal blocked"):
        dbops_mcp._resolve_db_path(str(tmp_path.parent / "outside.db"))


def test_securityops_tls_check_blocks_ssrf():
    for target in ("127.0.0.1", "169.254.169.254", "10.0.0.1", "localhost"):
        res = SecurityOpsMCP.check_tls_certificate(target)
        assert res["valid"] is False
        assert "SSRF blocked" in res["error"]


def test_gateway_strict_cors_and_readonly_mutating_gate():
    client = TestClient(app)
    bad_cors = client.options(
        "/health",
        headers={"Origin": "https://evil.example.net", "Access-Control-Request-Method": "GET"},
    )
    assert bad_cors.headers.get("access-control-allow-origin") is None

    blocked = client.post(
        "/dbops/call/apply_migrations",
        headers={"X-Execution-Mode": "READ_ONLY"},
        json={"db_path": "demo.db"},
    )
    assert blocked.status_code == 403
    assert "PolicyGate violation" in blocked.json()["error"]
