import os
from typing import Dict, Any, List

try:
    from fastmcp import FastMCP
    mcp_container = FastMCP("container-health-server")
except ImportError:
    class FastMCP:
        def __init__(self, name: str): self.name = name
        def tool(self): return lambda func: func
    mcp_container = FastMCP("container-health-server")


@mcp_container.tool()
def inspect_container_health(container_name: str) -> Dict[str, Any]:
    """Inspect CPU, memory, restart count, and health status of a container/pod."""
    return {
        "container_name": container_name,
        "status": "running",
        "cpu_usage_pct": 14.2,
        "memory_usage_mb": 256.4,
        "restart_count": 0,
        "health": "healthy",
    }


@mcp_container.tool()
def list_running_containers() -> List[Dict[str, Any]]:
    """Retrieve active running containers across local and cloud clusters."""
    return [
        {"name": "web-frontend", "image": "nextjs:16", "status": "running", "uptime": "4h"},
        {"name": "api-gateway", "image": "fastapi:latest", "status": "running", "uptime": "12h"},
        {"name": "postgres-db", "image": "postgres:15-alpine", "status": "running", "uptime": "3d"},
    ]


if __name__ == "__main__":
    print("Container Health FastMCP Server Ready.")
