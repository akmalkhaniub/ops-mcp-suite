# Proposed New Features & 2026 MCP Spec Roadmap (`ops-mcp-suite`)

**Scope:** Alignment upgrades for Pluralsight *Model Context Protocol: Security and Safety* and *Model Context Protocol: Advanced Features* (complementing [`docs/PRODUCTION_IMPROVEMENT_PLAN_2026-11-06.md`](./PRODUCTION_IMPROVEMENT_PLAN_2026-11-06.md)).  
**Baseline Reviewed:** [`gateway.py`](../gateway.py), [`requirements.txt`](../requirements.txt), [`dbops_mcp.py`](../dbops_mcp.py), [`secrets_mcp.py`](../secrets_mcp.py), [`github_mcp.py`](../github_mcp.py), [`securityops_mcp.py`](../securityops_mcp.py), [`SECURITY.md`](../SECURITY.md)

---

## Current Baseline Gaps

- [`gateway.py`](../gateway.py#L4-L168) exposes legacy `/{server_id}/sse` framing and an unauthenticated REST proxy, with `allow_origins=["*"]` + `allow_credentials=True` ([`gateway.py`](../gateway.py#L89-L95)).
- Individual servers (`dbops_mcp.py`, `secrets_mcp.py`, `github_mcp.py`, etc.) import `from mcp.server.fastmcp import FastMCP` (MCP v1 pattern, [`requirements.txt`](../requirements.txt#L1-L2)).
- [`_resolve_db_path`](../dbops_mcp.py#L46-L55) resolves arbitrary `Path(db_path).resolve()` filesystem paths without confining access to a configured sandbox workspace directory.
- Tool schemas lack strict `additionalProperties: false` / length bounds, `ToolAnnotations` metadata, output redaction for secrets/tokens, and async Task tracking for long-running infra calls.

---

## Priority 1 — Transport Modernization & Security Hardening (*Security & Safety*)

### 1. Migrate from Legacy `/sse` & `FastMCP` v1 to Stateless HTTP / MCP SDK v2 (`MCPServer`)
- **Course Mapping:** *Security & Safety* (LO 2), *Advanced Features* (LO 1)
- **Target Files:** [`requirements.txt`](../requirements.txt), [`gateway.py`](../gateway.py), `devops_mcp.py`, `mlops_mcp.py`, `agentops_mcp.py`, `dbops_mcp.py`, `github_mcp.py`, `secrets_mcp.py`
- **Features to Add:**
  - Upgrade to MCP Python SDK v2 (`mcp.server.mcpserver.MCPServer`), retiring the deprecated `/{server_id}/sse` framing in [`gateway.py`](../gateway.py#L4-L168) in favor of stateless Streamable HTTP alongside `stdio` for local desktop/IDE use (`docs/claude_desktop_config.json`).
  - Gate `[SIMULATED]` fallback behavior behind an explicit `OPS_MCP_ALLOW_MOCK=true` startup config so production deployments fail closed instead of silently returning mock data.

### 2. OAuth 2.1 Resource Server + RFC 9728 + Scope-Filtered Tools + Strict CORS
- **Course Mapping:** *Security & Safety* (LO 2, LO 3, LO 4)
- **Target Files:** [`gateway.py`](../gateway.py#L89-L180), `auth_middleware.py` (new)
- **Features to Add:**
  - Serve `GET /.well-known/oauth-protected-resource` (RFC 9728) and challenge missing/invalid Bearer tokens with `401` + `WWW-Authenticate: Bearer resource_metadata="..."`.
  - Validate JWT signature (JWKS), `iss`, `aud`, and `exp`, replacing wildcard CORS (`gateway.py:89-95`) with explicit `OPS_CORS_ALLOWED_ORIGINS` and `expose_headers=["WWW-Authenticate"]`.
  - Expand `MUTATING_TOOLS` (`gateway.py:122-132`) into scope-mapped policies (`ops.read`, `ops.devops.write`, `ops.secrets.admin`, etc.) and hide unauthorized tools from `GET /{server_id}/tools` and `tools/list`.

### 3. Path-Traversal Confinement, Strict Validation & Log/Output Secret Redaction
- **Course Mapping:** *Security & Safety* (LO 6, LO 7)
- **Target Files:** [`dbops_mcp.py`](../dbops_mcp.py#L46-L60), [`secrets_mcp.py`](../secrets_mcp.py), [`github_mcp.py`](../github_mcp.py), `gateway.py`
- **Features to Add:**
  - Confine `_resolve_db_path` (`dbops_mcp.py:46-55`) and `clone_database` paths inside an `OPS_DB_WORKSPACE_ROOT` directory using `Path.resolve().is_relative_to(...)` to block arbitrary host filesystem reads/writes.
  - Validate domain/URL arguments in [`securityops_mcp.py`](../securityops_mcp.py#L13-L33) (`check_tls_certificate`) and HTTP fetchers against an SSRF blocklist (rejecting loopback, link-local `169.254.169.254`, and RFC 1918 private IPs unless explicitly allowlisted).
  - Add a shared output/log scrubber preventing Fernet keys, `GITHUB_TOKEN`, AWS credentials, or retrieved `secrets_mcp.py` secret values from leaking into structured logs or LLM-visible error messages.

### 4. MCP `ToolAnnotations` Across All 6 Servers
- **Course Mapping:** *Security & Safety* (LO 6)
- **Target Files:** All 6 server modules
- **Features to Add:**
  - Annotate read-only queries (`run_query`, `list_tables`, `list_repos`, `check_tls_certificate`, `audit_dependency_manifest`) with `readOnlyHint=True, destructiveHint=False`.
  - Annotate infra/credential mutators (`provision_s3_bucket`, `deploy_docker_container`, `apply_migrations`, `store_secret`, `delete_secret`, `rotate_secret`) with `readOnlyHint=False, destructiveHint=True`.

---

## Priority 2 — Advanced MCP Features (*Advanced Features*)

### 5. Async MCP Tasks & Native Elicitation (`input-required` + URL Mode) for High-Risk Ops
- **Course Mapping:** *Advanced Features* (LO 2, LO 3), *Security & Safety* (LO 7)
- **Target Files:** `devops_mcp.py`, `dbops_mcp.py`, `mlops_mcp.py`, `secrets_mcp.py`, `gateway.py`
- **Features to Add:**
  - Convert long-running operations (`deploy_docker_container`, `trigger_fine_tuning`, `provision_vector_db`, `apply_migrations`) to return **MCP Tasks** handles with SQLite persistence, progress notifications, and cancellation support.
  - Protect destructive infra/secret actions (`rotate_secret`, `apply_migrations`, `provision_s3_bucket`) with **form elicitation (`input-required`)** confirmations, and route sensitive key/token provisioning through **URL-mode elicitation** so plaintext secrets never travel inside LLM tool arguments.

### 6. `structuredContent`, `resource_link` & Prompt/Resource Completions
- **Course Mapping:** *Advanced Features* (LO 4)
- **Target Files:** `agentops_mcp.py`, `dbops_mcp.py`, `github_mcp.py`
- **Features to Add:**
  - Return typed `structuredContent` alongside concise summaries for SQL query results (`dbops_mcp.py`), TLS/CVE audits (`securityops_mcp.py`), and eval traces (`agentops_mcp.py`).
  - Return `resource_link` URIs (`ops://traces/{run_id}`, `ops://db/schema/{db_id}`) for large outputs and charts, plus `completion/complete` autocomplete for repository names, DB table names, and prompt templates.

---

## Verification Plan

- Add automated pytest coverage in [`tests/test_mock_gateway.py`](../tests/test_mock_gateway.py) and [`tests/test_ops_mcp.py`](../tests/test_ops_mcp.py) verifying:
  - RFC 9728 `401` discovery, scope-filtered `tools/list`, and strict CORS origin rejection.
  - Path-traversal (`../`) blocking in `dbops_mcp.py`, SSRF private-IP rejection in `securityops_mcp.py`, and secret masking across logs/tool outputs.
  - `ToolAnnotations` presence on all tools and Task / `input-required` confirmation handling for mutating operations.
