"""
Secrets Manager MCP Server — Encrypted local secrets vault.

Provides tools for storing, retrieving, rotating, and managing secrets that
are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).  The vault is
persisted as an encrypted JSON file (``./secrets_vault.enc``).

Encryption key handling:
    1. If the ``VAULT_MASTER_KEY`` environment variable is set, its value is
       used as the Fernet key directly (must be a valid 32-byte URL-safe
       base64-encoded key).
    2. Otherwise, the server auto-generates a key and saves it to
       ``./vault.key`` on first run.

Environment variables:
    VAULT_MASTER_KEY  — Optional Fernet-compatible encryption key.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("secrets_mcp")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP("Secrets Manager MCP Server")

# ---------------------------------------------------------------------------
# Paths & Configuration
# ---------------------------------------------------------------------------
VAULT_FILE = Path("./secrets_vault.enc")
KEY_FILE = Path("./vault.key")


# ===================================================================
# SecureVault helper class
# ===================================================================

class SecureVault:
    """Manages an encrypted JSON vault backed by a local file.

    The vault structure (decrypted) is a dict of secret entries::

        {
            "MY_KEY": {
                "value": "supersecret",
                "description": "Production DB password",
                "created_at": "2026-05-22T11:00:00+00:00",
                "updated_at": "2026-05-22T11:00:00+00:00",
                "_previous": null
            },
            ...
        }
    """

    def __init__(self, vault_path: Path, key_path: Path) -> None:
        self._vault_path = vault_path
        self._key_path = key_path
        self._fernet: Fernet = self._load_or_create_fernet()

    # ---- key management ------------------------------------------------

    def _load_or_create_fernet(self) -> Fernet:
        """Resolve the Fernet instance from env-var or key file."""
        env_key = os.environ.get("VAULT_MASTER_KEY")
        if env_key:
            logger.info("Using VAULT_MASTER_KEY from environment.")
            try:
                return Fernet(env_key.encode())
            except (ValueError, Exception) as exc:
                raise ValueError(
                    "VAULT_MASTER_KEY is not a valid Fernet key. "
                    "It must be 32 URL-safe base64-encoded bytes."
                ) from exc

        # Auto-generate and persist
        if self._key_path.exists():
            logger.info("Loading encryption key from %s.", self._key_path)
            key = self._key_path.read_bytes().strip()
        else:
            logger.info("Generating new encryption key -> %s.", self._key_path)
            key = Fernet.generate_key()
            self._key_path.write_bytes(key)
            # Restrict permissions best-effort (Windows may ignore this)
            try:
                os.chmod(self._key_path, 0o600)
            except OSError:
                pass

        return Fernet(key)

    # ---- vault I/O -----------------------------------------------------

    def _load_vault(self) -> dict[str, dict[str, Any]]:
        """Decrypt and deserialize the vault file.  Returns empty dict if
        the file does not exist yet."""
        if not self._vault_path.exists():
            return {}
        try:
            encrypted = self._vault_path.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted)
        except InvalidToken:
            logger.error("Failed to decrypt vault — wrong key or corrupted file.")
            raise PermissionError(
                "Cannot decrypt the vault. The encryption key may have "
                "changed or the vault file is corrupted."
            )
        except json.JSONDecodeError:
            logger.error("Vault contains invalid JSON after decryption.")
            raise ValueError("Vault file is corrupted (invalid JSON).")

    def _save_vault(self, data: dict[str, dict[str, Any]]) -> None:
        """Serialize and encrypt the vault dict, then write to disk."""
        raw = json.dumps(data, indent=2, default=str).encode()
        encrypted = self._fernet.encrypt(raw)
        self._vault_path.write_bytes(encrypted)
        logger.info("Vault saved (%d secrets, %d bytes encrypted).", len(data), len(encrypted))

    # ---- timestamp helper -----------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    # ---- public API ----------------------------------------------------

    def store(self, key: str, value: str, description: str = "") -> str:
        """Store or update a secret in the vault."""
        vault = self._load_vault()
        is_update = key in vault
        vault[key] = {
            "value": value,
            "description": description,
            "created_at": vault[key]["created_at"] if is_update else self._now_iso(),
            "updated_at": self._now_iso(),
            "_previous": vault[key]["value"] if is_update else None,
        }
        self._save_vault(vault)
        action = "updated" if is_update else "created"
        return f"Secret '{key}' {action} successfully."

    def get(self, key: str) -> str:
        """Retrieve a decrypted secret value."""
        vault = self._load_vault()
        entry = vault.get(key)
        if entry is None:
            raise KeyError(f"Secret '{key}' not found in the vault.")
        return entry["value"]

    def list_all(self) -> list[dict[str, str]]:
        """Return a list of secret metadata with masked values."""
        vault = self._load_vault()
        result: list[dict[str, str]] = []
        for k, v in vault.items():
            raw_val = v.get("value", "")
            masked = raw_val[:4] + "***" if len(raw_val) > 4 else "***"
            result.append({
                "key": k,
                "masked_value": masked,
                "description": v.get("description", ""),
                "created_at": v.get("created_at", ""),
                "updated_at": v.get("updated_at", ""),
            })
        return result

    def delete(self, key: str) -> str:
        """Remove a secret from the vault."""
        vault = self._load_vault()
        if key not in vault:
            raise KeyError(f"Secret '{key}' not found in the vault.")
        del vault[key]
        self._save_vault(vault)
        return f"Secret '{key}' deleted successfully."

    def rotate(self, key: str) -> str:
        """Rotate a secret: generate a new random 32-char hex value,
        preserve the old value in ``_previous``."""
        vault = self._load_vault()
        if key not in vault:
            raise KeyError(f"Secret '{key}' not found in the vault.")
        old_value = vault[key]["value"]
        new_value = secrets.token_hex(16)  # 32 hex characters
        vault[key]["_previous"] = old_value
        vault[key]["value"] = new_value
        vault[key]["updated_at"] = self._now_iso()
        self._save_vault(vault)
        return new_value


# ---------------------------------------------------------------------------
# Singleton vault instance
# ---------------------------------------------------------------------------
try:
    _vault = SecureVault(VAULT_FILE, KEY_FILE)
except (ValueError, PermissionError) as _init_err:
    logger.critical("Vault initialisation failed: %s", _init_err)
    _vault = None  # type: ignore[assignment]
    _INIT_ERROR = str(_init_err)


def _ensure_vault() -> SecureVault:
    """Return the vault instance or raise if initialisation failed."""
    if _vault is None:
        raise RuntimeError(f"Vault is unavailable: {_INIT_ERROR}")
    return _vault


# ===================================================================
# Tools
# ===================================================================

@mcp.tool()
def store_secret(key: str, value: str, description: str = "") -> str:
    """Encrypt and store a secret in the local vault.

    If the key already exists its value is updated and the previous value
    is preserved internally.

    Args:
        key: Unique identifier for the secret (e.g. 'PROD_DB_PASSWORD').
        value: The secret value to store.
        description: Optional human-readable description of the secret.

    Returns:
        Confirmation message.
    """
    if not key.strip():
        return "Error: 'key' cannot be empty."
    if not value:
        return "Error: 'value' cannot be empty."

    try:
        vault = _ensure_vault()
        result = vault.store(key.strip(), value, description.strip())
        logger.info("store_secret: key=%s", key)
        return result
    except (PermissionError, ValueError, RuntimeError) as exc:
        logger.error("store_secret error: %s", exc)
        return f"Error: {exc}"


@mcp.tool()
def get_secret(key: str) -> str:
    """Decrypt and retrieve a secret value from the vault.

    Args:
        key: The identifier of the secret to retrieve.

    Returns:
        The decrypted secret value, or an error message.
    """
    if not key.strip():
        return "Error: 'key' cannot be empty."

    try:
        vault = _ensure_vault()
        secret_value = vault.get(key.strip())
        logger.info("get_secret: key=%s (retrieved)", key)
        return f"Secret '{key}':\n{secret_value}"
    except KeyError as exc:
        return f"Error: {exc}"
    except (PermissionError, ValueError, RuntimeError) as exc:
        logger.error("get_secret error: %s", exc)
        return f"Error: {exc}"


@mcp.tool()
def list_secrets() -> str:
    """List all secrets stored in the vault with masked values.

    Values are masked: only the first 4 characters are shown, followed by
    '***'.  Descriptions and timestamps are included.

    Returns:
        Formatted listing of all secrets, or a message if the vault is empty.
    """
    try:
        vault = _ensure_vault()
        entries = vault.list_all()

        if not entries:
            return "The vault is empty — no secrets stored."

        lines = [f"Secrets Vault ({len(entries)} entries):"]
        lines.append("-" * 60)
        for e in entries:
            lines.append(
                f"  🔑 {e['key']}\n"
                f"     Value : {e['masked_value']}\n"
                f"     Desc  : {e['description'] or '(none)'}\n"
                f"     Created: {e['created_at']}  Updated: {e['updated_at']}"
            )
        return "\n".join(lines)

    except (PermissionError, ValueError, RuntimeError) as exc:
        logger.error("list_secrets error: %s", exc)
        return f"Error: {exc}"


@mcp.tool()
def delete_secret(key: str) -> str:
    """Remove a secret from the vault permanently.

    Args:
        key: The identifier of the secret to delete.

    Returns:
        Confirmation message or an error if the key is not found.
    """
    if not key.strip():
        return "Error: 'key' cannot be empty."

    try:
        vault = _ensure_vault()
        result = vault.delete(key.strip())
        logger.info("delete_secret: key=%s (deleted)", key)
        return result
    except KeyError as exc:
        return f"Error: {exc}"
    except (PermissionError, ValueError, RuntimeError) as exc:
        logger.error("delete_secret error: %s", exc)
        return f"Error: {exc}"


@mcp.tool()
def rotate_secret(key: str) -> str:
    """Rotate a secret by generating a new random value.

    A new 32-character hexadecimal value is generated and stored.  The
    previous value is preserved in a ``_previous`` field inside the vault
    so it can be referenced if needed during migration.

    Args:
        key: The identifier of the secret to rotate.

    Returns:
        The newly generated secret value, or an error message.
    """
    if not key.strip():
        return "Error: 'key' cannot be empty."

    try:
        vault = _ensure_vault()
        new_value = vault.rotate(key.strip())
        logger.info("rotate_secret: key=%s (rotated)", key)
        return (
            f"Secret '{key}' rotated successfully.\n"
            f"  New value: {new_value}\n"
            f"  (Previous value preserved in vault)"
        )
    except KeyError as exc:
        return f"Error: {exc}"
    except (PermissionError, ValueError, RuntimeError) as exc:
        logger.error("rotate_secret error: %s", exc)
        return f"Error: {exc}"


@mcp.tool()
def generate_api_key(prefix: str = "sk", length: int = 48) -> str:
    """Generate a cryptographically secure API key.

    The key format is ``{prefix}_{random_hex}``.  The random portion is
    generated using ``secrets.token_hex`` for cryptographic strength.

    **Note:** This tool does NOT automatically store the key in the vault.
    Use ``store_secret`` separately if you want to persist it.

    Args:
        prefix: Key prefix (default 'sk'). Kept short and alphanumeric.
        length: Total desired character length of the random hex portion.
                Must be between 16 and 128. Defaults to 48.

    Returns:
        The generated API key string.
    """
    # Validate prefix
    cleaned_prefix = prefix.strip()
    if not cleaned_prefix.isalnum():
        return "Error: 'prefix' must be alphanumeric (e.g. 'sk', 'pk', 'api')."

    # Validate length
    if not (16 <= length <= 128):
        return "Error: 'length' must be between 16 and 128."

    # token_hex(n) produces 2*n hex chars, so we need length//2 bytes
    hex_bytes = (length + 1) // 2  # round up
    random_part = secrets.token_hex(hex_bytes)[:length]

    api_key = f"{cleaned_prefix}_{random_part}"
    logger.info("generate_api_key: prefix=%s, length=%d", cleaned_prefix, length)

    return (
        f"Generated API Key:\n"
        f"  {api_key}\n\n"
        f"⚠️  This key is NOT stored in the vault. "
        f"Use store_secret() to persist it."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting Secrets Manager MCP Server (vault=%s)", VAULT_FILE.resolve())
    mcp.run()
