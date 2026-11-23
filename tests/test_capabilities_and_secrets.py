import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from mcp.server.lowlevel import NotificationOptions

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agentops_mcp
import dbops_mcp
import devops_mcp
import github_mcp
import mlops_mcp
import secrets_mcp
from gateway import app, rate_limiter
from secrets_mcp import SecureVault


@pytest.fixture(autouse=True)
def reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


def test_all_six_servers_advertise_mcp_2026_capabilities():
    servers = {
        "agentops": agentops_mcp,
        "dbops": dbops_mcp,
        "devops": devops_mcp,
        "github": github_mcp,
        "mlops": mlops_mcp,
        "secrets": secrets_mcp,
    }
    client = TestClient(app)

    for server_id, mod in servers.items():
        # Verify underlying FastMCP initialization options expose all 4 capabilities
        init_opts = mod.mcp._mcp_server.create_initialization_options(NotificationOptions())
        caps = init_opts.capabilities.model_dump(exclude_none=True)
        for cap_name in ("prompts", "resources", "tools", "logging"):
            assert cap_name in caps, f"{server_id} missing '{cap_name}' capability"

        # Verify JSON-RPC initialize negotiation via gateway
        resp = client.post(
            f"/{server_id}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {}},
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["jsonrpc"] == "2.0"
        assert payload["id"] == 1
        result = payload["result"]
        assert result["protocolVersion"] == "2025-11-25"
        for cap_name in ("prompts", "resources", "tools", "logging"):
            assert cap_name in result["capabilities"]
        assert result["serverInfo"]["name"]


def test_rotate_secret_reencrypts_with_ttl_and_expires_old_key(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    vault = SecureVault(tmp_path / "vault.enc", tmp_path / "vault.key")
    monkeypatch.setattr(secrets_mcp, "_vault", vault)

    assert "created" in secrets_mcp.store_secret("DB_PASS", "initial-secret-1", "Primary DB")
    before = datetime.now(tz=timezone.utc)

    res = secrets_mcp.rotate_secret("DB_PASS", "rotated-secret-2", ttl_days=30)
    assert "rotated successfully" in res
    assert "EXPIRED; expired_at=" in res
    assert "rotated-secret-2" not in res  # Never leak raw secret in tool output

    # Decrypted current value matches new_value
    assert vault.get("DB_PASS") == "rotated-secret-2"

    # Metadata tracks fresh rotation timestamp, 30-day expiry, and old key expiration
    meta = vault.get_metadata("DB_PASS")
    assert meta["has_previous"] is True
    assert meta["ttl_days"] == 30
    assert meta["previous_status"].startswith("EXPIRED; expired_at=")
    assert meta["previous_expires_at"] is not None
    expires_dt = datetime.fromisoformat(meta["expires_at"])
    assert expires_dt > before + timedelta(days=29)

    # Reject invalid ttl_days
    err = secrets_mcp.rotate_secret("DB_PASS", "bad-ttl", ttl_days=0)
    assert err.startswith("Error:")
