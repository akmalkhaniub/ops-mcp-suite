"""
In-memory IP and API-key aware token bucket rate limiter for Ops MCP Gateway.

Keys callers by hashed API key / Bearer token when provided, falling back to
client IP address, enforcing a configurable requests-per-minute budget.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request


@dataclass(frozen=True)
class RateLimitDecision:
    """Result of evaluating a single request against a token bucket."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class TokenBucketRateLimiter:
    """Thread-safe in-memory token bucket rate limiter keyed by caller identity."""

    def __init__(
        self,
        requests_per_minute: int = 120,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.requests_per_minute = requests_per_minute
        self.refill_rate = requests_per_minute / 60.0
        self._clock: Callable[[], float] = clock or time.monotonic
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def set_clock(self, clock: Callable[[], float] | None) -> None:
        """Override the monotonic clock (useful for deterministic unit tests)."""
        with self._lock:
            self._clock = clock or time.monotonic

    def configure(self, requests_per_minute: int) -> None:
        """Update the rate limit and reset active buckets."""
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        with self._lock:
            self.requests_per_minute = requests_per_minute
            self.refill_rate = requests_per_minute / 60.0
            self._buckets.clear()

    def reset(self) -> None:
        """Clear all tracked caller buckets."""
        with self._lock:
            self._buckets.clear()

    @staticmethod
    def resolve_client_key(request: Request) -> str:
        """Derive a stable, non-sensitive bucket key from API key, Bearer token, or IP."""
        api_key = request.headers.get("X-Ops-Api-Key", "").strip()
        if api_key:
            digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
            return f"apikey:{digest}"

        auth = request.headers.get("Authorization", "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token:
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
                return f"bearer:{digest}"

        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        client_host = forwarded or (request.client.host if request.client else "unknown")
        return f"ip:{client_host}"

    def consume(self, key: str, now: float | None = None) -> RateLimitDecision:
        """Attempt to consume one token from the bucket associated with ``key``."""
        current = self._clock() if now is None else now
        with self._lock:
            capacity = float(self.requests_per_minute)
            tokens, last_ts = self._buckets.get(key, (capacity, current))
            elapsed = max(0.0, current - last_ts)
            tokens = min(capacity, tokens + elapsed * self.refill_rate)

            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = (tokens, current)
                return RateLimitDecision(
                    allowed=True,
                    limit=self.requests_per_minute,
                    remaining=max(0, int(math.floor(tokens))),
                    retry_after_seconds=0,
                )

            self._buckets[key] = (tokens, current)
            deficit = 1.0 - tokens
            retry_after = max(1, int(math.ceil(deficit / self.refill_rate)))
            return RateLimitDecision(
                allowed=False,
                limit=self.requests_per_minute,
                remaining=0,
                retry_after_seconds=retry_after,
            )


def default_rate_limit_rpm() -> int:
    """Read OPS_RATE_LIMIT_PER_MINUTE safely, defaulting to 120 req/min."""
    raw = os.environ.get("OPS_RATE_LIMIT_PER_MINUTE", "120").strip()
    try:
        val = int(raw)
        return val if val > 0 else 120
    except ValueError:
        return 120
