"""
Ops MCP Gateway — Production FastAPI application that serves all MCP servers as SSE endpoints.

Each MCP server is mounted at its own path:
    /devops/sse   -> DevOps Tools
    /mlops/sse    -> MLOps Tools
    /agentops/sse -> AgentOps Tools
    /dbops/sse    -> DBOps Tools
    /github/sse   -> GitHub Tools
    /secrets/sse  -> Secrets Manager

This allows a single Cloud Run service to host the entire Ops platform.
"""

import logging
import subprocess
import sys
import os
import json
import asyncio
import inspect
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("ops-gateway")

# ── Server Registry ──────────────────────────────────────────────────────────
MCP_SERVERS = {
    "devops": {
        "module": "devops_mcp",
        "name": "DevOps Tools",
        "description": "Cloud infrastructure, IAM, secrets, health checks, container deployment",
    },
    "mlops": {
        "module": "mlops_mcp",
        "name": "MLOps Tools",
        "description": "Model registry, fine-tuning, vector DB provisioning, metrics",
    },
    "agentops": {
        "module": "agentops_mcp",
        "name": "AgentOps Tools",
        "description": "Tracing, evaluation harness, prompt registry, observability",
    },
    "dbops": {
        "module": "dbops_mcp",
        "name": "DBOps Tools",
        "description": "Database provisioning, migrations, queries, schema inspection",
    },
    "github": {
        "module": "github_mcp",
        "name": "GitHub Tools",
        "description": "Repository management, PRs, issues, code search",
    },
    "secrets": {
        "module": "secrets_mcp",
        "name": "Secrets Manager",
        "description": "Encrypted secret storage, rotation, API key generation",
    },
}


# ── App Lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ops MCP Gateway starting — %d servers registered", len(MCP_SERVERS))
    for key, info in MCP_SERVERS.items():
        logger.info("  /%s/sse -> %s", key, info["name"])
    yield
    logger.info("Ops MCP Gateway shutting down")


app = FastAPI(
    title="Ops MCP Gateway",
    description="A unified gateway serving 6 production MCP servers via SSE",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health & Discovery ────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "service": "Ops MCP Gateway",
        "version": "1.0.0",
        "status": "healthy",
        "servers": {
            key: {
                "name": info["name"],
                "description": info["description"],
                "endpoint": f"/{key}/sse",
            }
            for key, info in MCP_SERVERS.items()
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# Tools that mutate live infrastructure or secrets require elevated permission when X-Execution-Mode=READ_ONLY
MUTATING_TOOLS = {
    "provision_s3_bucket",
    "create_iam_policy",
    "deploy_docker_container",
    "manage_secrets",
    "promote_model",
    "provision_vector_db",
    "store_secret",
    "rotate_keys",
    "create_issue",
}


def _extract_mcp_tools(mcp_instance) -> dict:
    """Safely extract registered tools from a FastMCP instance without brittle reliance on a single internal layout."""
    if mcp_instance is None:
        return {}
    tool_mgr = getattr(mcp_instance, "_tool_manager", None)
    if tool_mgr and hasattr(tool_mgr, "_tools"):
        return dict(tool_mgr._tools)
    if hasattr(mcp_instance, "tools") and isinstance(mcp_instance.tools, dict):
        return dict(mcp_instance.tools)
    return {}


@app.get("/servers")
async def list_servers():
    """Returns metadata about all available MCP servers and their tools."""
    servers = []
    for key, info in MCP_SERVERS.items():
        # Dynamically import the module to list its tools
        tool_names = []
        try:
            mod = __import__(info["module"])
            mcp_instance = getattr(mod, "mcp", None)
            tool_names = list(_extract_mcp_tools(mcp_instance).keys())
        except Exception as e:
            logger.warning("Could not inspect tools for %s: %s", key, e)

        servers.append({
            "id": key,
            "name": info["name"],
            "description": info["description"],
            "endpoint": f"/{key}/sse",
            "tools": tool_names,
        })
    return {"servers": servers}


# ── SSE Proxy Endpoints ──────────────────────────────────────────────────────
# Each MCP server can be started as a subprocess and communicated with via stdio.
# For the SSE gateway approach, we provide a simple tool-listing + tool-calling
# REST API that proxies to each MCP server module directly (in-process).

@app.get("/{server_id}/tools")
async def list_tools(server_id: str):
    """List all tools available on a specific MCP server."""
    if server_id not in MCP_SERVERS:
        return JSONResponse(status_code=404, content={"error": f"Server '{server_id}' not found"})

    info = MCP_SERVERS[server_id]
    try:
        mod = __import__(info["module"])
        mcp_instance = getattr(mod, "mcp", None)
        registered = _extract_mcp_tools(mcp_instance)
        if registered:
            tools = []
            for name, tool in registered.items():
                tools.append({
                    "name": name,
                    "description": getattr(tool, "description", str(getattr(tool, "fn", None).__doc__ or "")),
                    "execution_tier": "LIVE_MUTATION" if name in MUTATING_TOOLS else "READ_ONLY",
                })
            return {"server": info["name"], "tools": tools}
    except Exception as e:
        logger.error("Error listing tools for %s: %s", server_id, e)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return {"server": info["name"], "tools": []}


@app.post("/{server_id}/call/{tool_name}")
async def call_tool(server_id: str, tool_name: str, request: Request):
    """Call a specific tool on a specific MCP server with JSON arguments and execution-mode policy gating."""
    if server_id not in MCP_SERVERS:
        return JSONResponse(status_code=404, content={"error": f"Server '{server_id}' not found"})

    # Enforce optional API key & READ_ONLY execution harness guard
    configured_key = os.environ.get("OPS_GATEWAY_API_KEY")
    if configured_key:
        provided_key = request.headers.get("X-Ops-Api-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ")
        if provided_key != configured_key:
            return JSONResponse(status_code=401, content={"error": "Unauthorized: invalid or missing X-Ops-Api-Key"})

    exec_mode = request.headers.get("X-Execution-Mode", "FULL").upper()
    if exec_mode == "READ_ONLY" and tool_name in MUTATING_TOOLS:
        return JSONResponse(
            status_code=403,
            content={
                "error": f"PolicyGate violation: mutating tool '{tool_name}' is blocked under X-Execution-Mode=READ_ONLY"
            },
        )

    info = MCP_SERVERS[server_id]
    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        mod = __import__(info["module"])
        mcp_instance = getattr(mod, "mcp", None)
        registered = _extract_mcp_tools(mcp_instance)
        if registered:
            tool = registered.get(tool_name)
            if not tool:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"Tool '{tool_name}' not found on server '{server_id}'"},
                )
            # Call the tool function
            if inspect.iscoroutinefunction(tool.fn):
                result = await tool.fn(**body)
            else:
                result = tool.fn(**body)
            return {"server": server_id, "tool": tool_name, "result": result}
    except TypeError as e:
        logger.warning("Invalid arguments for %s/%s: %s", server_id, tool_name, e)
        return JSONResponse(status_code=422, content={"error": f"Invalid tool arguments: {e}"})
    except Exception as e:
        logger.error("Error calling %s/%s: %s", server_id, tool_name, e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
