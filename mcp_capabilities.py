"""
Shared MCP 2025/2026 JSON-RPC capability negotiation helpers for Ops MCP servers.

Registers logging capability support on FastMCP servers and constructs standard
``initialize`` responses reporting ``prompts``, ``resources``, ``tools``, and
``logging`` capabilities.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.lowlevel import NotificationOptions
from mcp.types import LoggingLevel

SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

_LEVEL_MAP: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "alert": logging.CRITICAL,
    "emergency": logging.CRITICAL,
}


def configure_mcp_capabilities(mcp_instance: Any, server_version: str = "1.0.0") -> None:
    """Enable logging capability negotiation and version metadata on a FastMCP server."""
    lowlevel = getattr(mcp_instance, "_mcp_server", None)
    if lowlevel is None:
        return

    if not getattr(lowlevel, "version", None):
        lowlevel.version = server_version

    @lowlevel.set_logging_level()
    async def _handle_set_logging_level(level: LoggingLevel) -> None:
        py_level = _LEVEL_MAP.get(str(level).lower(), logging.INFO)
        logging.getLogger(getattr(lowlevel, "name", "ops-mcp")).setLevel(py_level)


def negotiate_protocol_version(requested: str | None) -> str:
    """Negotiate the MCP protocol version per 2025/2026 specification."""
    if requested and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return SUPPORTED_PROTOCOL_VERSIONS[0]


def build_initialize_result(
    mcp_instance: Any,
    requested_protocol_version: str | None = None,
) -> dict[str, Any]:
    """Build a standard MCP JSON-RPC ``initialize`` result payload."""
    lowlevel = mcp_instance._mcp_server
    init_opts = lowlevel.create_initialization_options(NotificationOptions())
    raw_caps = init_opts.capabilities.model_dump(exclude_none=True)

    capabilities: dict[str, Any] = {
        "prompts": raw_caps.get("prompts", {"listChanged": False}),
        "resources": raw_caps.get("resources", {"subscribe": False, "listChanged": False}),
        "tools": raw_caps.get("tools", {"listChanged": False}),
        "logging": raw_caps.get("logging", {}),
    }
    if raw_caps.get("experimental"):
        capabilities["experimental"] = raw_caps["experimental"]

    return {
        "protocolVersion": negotiate_protocol_version(requested_protocol_version),
        "capabilities": capabilities,
        "serverInfo": {
            "name": init_opts.server_name,
            "version": init_opts.server_version or "1.0.0",
        },
    }
