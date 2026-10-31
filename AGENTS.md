# AGENTS.md — Autonomous Agent Operating Contract

## 🎯 Repository Purpose & Architecture
`ops-mcp-suite` is a modular micro-MCP platform providing 6 specialized Model Context Protocol servers (DevOps, MLOps, AgentOps, DBOps, GitHub, Secrets) unified under a FastAPI gateway supporting both standard `stdio` and serverless HTTP/SSE endpoints.

### Tech Stack
- **Language**: Python 3.10+
- **Frameworks**: FastAPI, Uvicorn, MCP SDK (`mcp`, `fastmcp`), Pydantic v2
- **Integrations**: AWS Boto3, Fernet Cryptography, SQLite/PostgreSQL, Octokit/GitHub API
- **Testing**: Pytest with Mock Fixtures

---

## ⚡ Autonomous Execution Protocol
1. Read the assigned task from `TASKS.json`.
2. Inspect target server files before making modifications.
3. Write clean, defensive Python code adhering strictly to the Quality Rules below.
4. Execute the single verification command:
   ```bash
   python -m pytest tests/ -v
   ```
5. If any test fails, analyze the traceback, self-heal the code, and re-run until all tests exit with code 0.
6. Commit changes with a conventional commit message: `feat(task-id): description` or `fix(task-id): description`.

---

## 🛡️ Non-Negotiable Quality Rules
- **No Live Cloud Calls in Tests**: All automated unit tests MUST use mocked AWS / GitHub / DB clients. Tests must run 100% offline in <5 seconds.
- **Pydantic Schema Validation**: All tool input arguments and output results must be defined using explicit Pydantic v2 schemas.
- **Zero Silent Exception Swallowing**: Never write `except Exception: pass`. Always log structured errors or raise appropriate MCP JSON-RPC error codes.
- **Defensive Cloud Operations**: Destructive actions (deleting S3 buckets, dropping tables) must include a `dry_run: bool = False` flag and return a safety preview when `dry_run=True`.

---

## 🧪 Verification Commands
- **Full Quality Gate**: `python -m pytest tests/ -v`
- **Run Individual Server**: `python devops_mcp.py` / `python gateway.py`
