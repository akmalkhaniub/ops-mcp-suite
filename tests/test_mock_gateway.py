import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gateway import app

client = TestClient(app)

def test_gateway_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"

def test_gateway_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "Ops MCP Gateway" in data["service"]
    assert "servers" in data

def test_gateway_servers():
    response = client.get("/servers")
    assert response.status_code == 200
    data = response.json()
    assert "servers" in data
    assert len(data["servers"]) >= 6
