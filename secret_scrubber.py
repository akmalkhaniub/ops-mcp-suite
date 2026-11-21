"""
Shared secret and credential redaction utilities for ops-mcp-suite.

Prevents Fernet master keys, GitHub tokens, AWS credentials, Bearer tokens,
and registered secret values from leaking into structured logs or LLM-visible
error messages.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED:GITHUB_PAT]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED:GITHUB_TOKEN]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:AWS_ACCESS_KEY]"),
    (re.compile(r"\b(?:sk|ls_api)_[A-Za-z0-9_-]{16,}\b"), "[REDACTED:API_KEY]"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1[REDACTED:BEARER]"),
    (
        re.compile(
            r"(?i)\b(VAULT_MASTER_KEY|GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY|OPS_GATEWAY_API_KEY|"
            r"OPS_JWT_HS256_SECRET|api_key|secret_key|password|token)\s*([:=])\s*([^\s,;'\"]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    # Standard 44-char URL-safe base64 Fernet keys ending in '='
    (re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}=(?!\w)"), "[REDACTED:FERNET_KEY]"),
)

_ENV_SECRET_VARS = (
    "GITHUB_TOKEN",
    "VAULT_MASTER_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "OPS_GATEWAY_API_KEY",
    "OPS_JWT_HS256_SECRET",
)


def redact_secrets(text: str, extra_secrets: Iterable[str] | None = None) -> str:
    """Redact known credential patterns and active environment secret values from *text*."""
    if not text:
        return text

    redacted = text
    # First replace literal runtime secrets (longest first to avoid partial leaks)
    literals: list[str] = []
    for var in _ENV_SECRET_VARS:
        val = os.environ.get(var, "")
        if val and len(val) >= 6:
            literals.append(val)
    if extra_secrets:
        for val in extra_secrets:
            if val and len(val) >= 6:
                literals.append(val)

    for secret_val in sorted(set(literals), key=len, reverse=True):
        redacted = redacted.replace(secret_val, "[REDACTED:SECRET]")

    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)

    return redacted


def redact_payload(value: Any, extra_secrets: Iterable[str] | None = None) -> Any:
    """Recursively redact secret patterns inside strings, lists, and dicts."""
    if isinstance(value, str):
        return redact_secrets(value, extra_secrets=extra_secrets)
    if isinstance(value, list):
        return [redact_payload(item, extra_secrets=extra_secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_payload(item, extra_secrets=extra_secrets) for item in value)
    if isinstance(value, dict):
        return {
            k: redact_payload(v, extra_secrets=extra_secrets)
            for k, v in value.items()
        }
    return value


class SecretRedactingFilter(logging.Filter):
    """Logging filter that scrubs credentials from formatted log messages and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(a) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        return True


def install_log_scrubber(logger: logging.Logger | None = None) -> None:
    """Attach a single SecretRedactingFilter instance to the target (or root) logger."""
    target = logger or logging.getLogger()
    if not any(isinstance(f, SecretRedactingFilter) for f in target.filters):
        target.addFilter(SecretRedactingFilter())
