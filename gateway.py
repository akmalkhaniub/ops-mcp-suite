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
import secrets
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

from auth_middleware import (
    AuthError,
    build_protected_resource_metadata,
    build_www_authenticate_header,
    get_required_scope,
    resolve_request_principal,
)
from mcp_capabilities import build_initialize_result
from rate_limiter import TokenBucketRateLimiter, default_rate_limit_rpm
from secret_scrubber import install_log_scrubber, redact_secrets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
install_log_scrubber()
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

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "OPS_CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:8080,http://localhost:8080,http://localhost:6274",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Ops-Api-Key", "X-Execution-Mode", "X-Ops-Scopes", "Mcp-Session-Id"],
    expose_headers=["WWW-Authenticate", "Mcp-Session-Id", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

rate_limiter = TokenBucketRateLimiter(requests_per_minute=default_rate_limit_rpm())
app.state.rate_limiter = rate_limiter


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Enforce per-API-key / per-IP token bucket rate limiting across gateway routes."""
    if request.method == "OPTIONS":
        return await call_next(request)

    limiter: TokenBucketRateLimiter = getattr(app.state, "rate_limiter", rate_limiter)
    client_key = limiter.resolve_client_key(request)
    decision = limiter.consume(client_key)
    if not decision.allowed:
        return JSONResponse(
            status_code=429,
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
            content={
                "error": "Rate limit exceeded. Maximum 120 requests per minute allowed.",
                "code": "RATE_LIMIT_EXCEEDED",
                "retry_after_seconds": decision.retry_after_seconds,
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    return response


# ── Health & Discovery ────────────────────────────────────────────────────────
@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request):
    """RFC 9728 OAuth 2.0 Protected Resource Metadata endpoint."""
    return build_protected_resource_metadata(str(request.base_url))
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
    "generate_bedrock_credentials",
    "create_iam_policy",
    "deploy_docker_container",
    "manage_secrets",
    "promote_model",
    "provision_vector_db",
    "trigger_fine_tuning",
    "store_secret",
    "delete_secret",
    "rotate_secret",
    "rotate_keys",
    "generate_api_key",
    "create_issue",
    "provision_database",
    "apply_migrations",
    "clone_database",
    "create_read_only_user",
    "create_langsmith_project",
    "run_eval_harness",
    "log_agent_trace",
    "create_prompt_template",
}


def _extract_annotations(tool: object, is_mutating: bool) -> dict:
    """Extract normalized MCP ToolAnnotations metadata from a FastMCP Tool object."""
    ann = getattr(tool, "annotations", None)
    if ann is not None:
        if hasattr(ann, "model_dump"):
            return ann.model_dump(exclude_none=True)
        if isinstance(ann, dict):
            return dict(ann)
    return {
        "readOnlyHint": not is_mutating,
        "destructiveHint": is_mutating,
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
async def list_tools(server_id: str, request: Request):
    """List tools available on a specific MCP server, filtered by caller OAuth scopes when present."""
    if server_id not in MCP_SERVERS:
        return JSONResponse(status_code=404, content={"error": f"Server '{server_id}' not found"})

    try:
        principal = resolve_request_principal(request, require_auth_override=False)
    except AuthError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            headers={"WWW-Authenticate": build_www_authenticate_header(request, error=exc.error)},
            content={"error": redact_secrets(exc.description)},
        )

    info = MCP_SERVERS[server_id]
    try:
        mod = __import__(info["module"])
        mcp_instance = getattr(mod, "mcp", None)
        registered = _extract_mcp_tools(mcp_instance)
        if registered:
            tools = []
            for name, tool in registered.items():
                is_mutating = name in MUTATING_TOOLS
                req_scope = get_required_scope(name, is_mutating=is_mutating)
                if not principal.has_scope(req_scope):
                    continue
                tools.append({
                    "name": name,
                    "description": getattr(tool, "description", str(getattr(tool, "fn", None).__doc__ or "")),
                    "execution_tier": "LIVE_MUTATION" if is_mutating else "READ_ONLY",
                    "required_scope": req_scope,
                    "annotations": _extract_annotations(tool, is_mutating=is_mutating),
                })
            return {"server": info["name"], "tools": tools}
    except Exception as e:
        logger.error("Error listing tools for %s: %s", server_id, e)
        return JSONResponse(status_code=500, content={"error": redact_secrets(str(e))})

    return {"server": info["name"], "tools": []}


@app.post("/{server_id}/call/{tool_name}")
async def call_tool(server_id: str, tool_name: str, request: Request):
    """Call a specific tool on a specific MCP server with OAuth/API-key, scope, and READ_ONLY policy gating."""
    if server_id not in MCP_SERVERS:
        return JSONResponse(status_code=404, content={"error": f"Server '{server_id}' not found"})

    try:
        principal = resolve_request_principal(request)
    except AuthError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            headers={"WWW-Authenticate": build_www_authenticate_header(request, error=exc.error)},
            content={"error": redact_secrets(exc.description)},
        )

    is_mutating = tool_name in MUTATING_TOOLS
    req_scope = get_required_scope(tool_name, is_mutating=is_mutating)
    if not principal.has_scope(req_scope):
        return JSONResponse(
            status_code=403,
            headers={
                "WWW-Authenticate": build_www_authenticate_header(
                    request, error="insufficient_scope", required_scope=req_scope
                )
            },
            content={
                "error": f"Insufficient scope: '{tool_name}' requires scope '{req_scope}'",
                "required_scope": req_scope,
            },
        )

    exec_mode = request.headers.get("X-Execution-Mode", "FULL").upper()
    if exec_mode == "READ_ONLY" and is_mutating:
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
        return JSONResponse(status_code=422, content={"error": redact_secrets(f"Invalid tool arguments: {e}")})
    except Exception as e:
        logger.error("Error calling %s/%s: %s", server_id, tool_name, e)
        return JSONResponse(status_code=500, content={"error": redact_secrets(str(e))})


def _jsonrpc_error(req_id, code: int, message: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
    )


@app.post("/{server_id}/mcp")
async def mcp_jsonrpc(server_id: str, request: Request):
    """MCP 2025/2026 JSON-RPC 2.0 endpoint supporting capability negotiation and tool dispatch."""
    if server_id not in MCP_SERVERS:
        return _jsonrpc_error(None, -32004, f"Server '{server_id}' not found", status_code=404)

    try:
        payload = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error: invalid JSON", status_code=400)

    if not isinstance(payload, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request: expected JSON object", status_code=400)

    req_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return _jsonrpc_error(req_id, -32600, "Invalid Request", status_code=400)

    info = MCP_SERVERS[server_id]
    mod = __import__(info["module"])
    mcp_instance = getattr(mod, "mcp", None)

    if method == "initialize":
        req_version = params.get("protocolVersion")
        result = build_initialize_result(mcp_instance, requested_protocol_version=req_version)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    if method == "notifications/initialized":
        return JSONResponse(status_code=202, content={"jsonrpc": "2.0", "status": "accepted"})

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        try:
            principal = resolve_request_principal(request, require_auth_override=False)
        except AuthError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                headers={"WWW-Authenticate": build_www_authenticate_header(request, error=exc.error)},
                content={"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": redact_secrets(exc.description)}},
            )
        registered = _extract_mcp_tools(mcp_instance)
        tools = []
        for name, tool in registered.items():
            is_mutating = name in MUTATING_TOOLS
            req_scope = get_required_scope(name, is_mutating=is_mutating)
            if not principal.has_scope(req_scope):
                continue
            tools.append({
                "name": name,
                "description": getattr(tool, "description", ""),
                "annotations": _extract_annotations(tool, is_mutating=is_mutating),
            })
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(tool_name, str) or not isinstance(arguments, dict):
            return _jsonrpc_error(req_id, -32602, "Invalid params: 'name' and 'arguments' required", status_code=400)
        try:
            principal = resolve_request_principal(request)
        except AuthError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                headers={"WWW-Authenticate": build_www_authenticate_header(request, error=exc.error)},
                content={"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": redact_secrets(exc.description)}},
            )
        is_mutating = tool_name in MUTATING_TOOLS
        req_scope = get_required_scope(tool_name, is_mutating=is_mutating)
        if not principal.has_scope(req_scope):
            return JSONResponse(
                status_code=403,
                headers={"WWW-Authenticate": build_www_authenticate_header(request, error="insufficient_scope", required_scope=req_scope)},
                content={"jsonrpc": "2.0", "id": req_id, "error": {"code": -32003, "message": f"Insufficient scope '{req_scope}'"}},
            )
        exec_mode = request.headers.get("X-Execution-Mode", "FULL").upper()
        if exec_mode == "READ_ONLY" and is_mutating:
            return _jsonrpc_error(req_id, -32003, f"PolicyGate violation: '{tool_name}' blocked under READ_ONLY", status_code=403)
        registered = _extract_mcp_tools(mcp_instance)
        tool = registered.get(tool_name)
        if not tool:
            return _jsonrpc_error(req_id, -32601, f"Tool '{tool_name}' not found", status_code=404)
        try:
            res = await tool.fn(**arguments) if inspect.iscoroutinefunction(tool.fn) else tool.fn(**arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": str(res)}], "isError": False}}
        except TypeError as exc:
            return _jsonrpc_error(req_id, -32602, redact_secrets(f"Invalid tool arguments: {exc}"), status_code=422)

    return _jsonrpc_error(req_id, -32601, f"Method '{method}' not found", status_code=404)


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
