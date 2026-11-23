import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gateway import app, rate_limiter


@pytest.fixture(autouse=True)
def reset_limiter():
    now = [1000.0]
    rate_limiter.configure(120)
    rate_limiter.set_clock(lambda: now[0])
    yield now
    rate_limiter.set_clock(None)
    rate_limiter.configure(120)


def test_gateway_rate_limit_enforces_120_rpm_and_returns_429_with_retry_after(reset_limiter):
    now = reset_limiter
    client = TestClient(app)
    headers = {"X-Ops-Api-Key": "agent-key-alpha"}

    for i in range(120):
        resp = client.get("/health", headers=headers)
        assert resp.status_code == 200, f"Unexpected status at request {i + 1}: {resp.status_code}"
        assert resp.headers["X-RateLimit-Limit"] == "120"

    blocked = client.get("/health", headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    body = blocked.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Rate limit exceeded" in body["error"]
    assert body["retry_after_seconds"] >= 1

    # Advance clock by 1 second (2 tokens refilled at 120 rpm) -> requests recover
    now[0] += 1.0
    recovered = client.get("/health", headers=headers)
    assert recovered.status_code == 200


def test_gateway_rate_limit_isolates_api_keys_and_ips():
    client = TestClient(app)

    for _ in range(120):
        assert client.get("/health", headers={"X-Ops-Api-Key": "key-one"}).status_code == 200

    # key-one is exhausted, but key-two and IP-only callers have separate buckets
    assert client.get("/health", headers={"X-Ops-Api-Key": "key-one"}).status_code == 429
    assert client.get("/health", headers={"X-Ops-Api-Key": "key-two"}).status_code == 200
    assert client.get("/health").status_code == 200
