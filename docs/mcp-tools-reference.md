# 📚 Ops MCP Suite — Tool Reference Manual

This document details all **6 micro-MCP servers** and their exposed tools available through standard `stdio` or the unified FastAPI SSE Gateway (`http://localhost:8080`).

---

## 1. 🔧 DevOps MCP (`devops_mcp.py`)
Cloud infrastructure provisioning, health checking, and container management.

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `create_s3_bucket` | `bucket_name: str, region: str = "us-east-1", versioning: bool = True` | Provisions an AWS S3 bucket with enforced versioning and security tags. |
| `check_service_health` | `service_url: str, timeout: int = 5` | Performs HTTP status checks, latency measurement, and SSL certificate verification. |
| `deploy_container` | `image_name: str, port: int, env_vars: dict = {}` | Deploys a Docker container locally or generates Cloud Run deployment manifests. |

---

## 2. 🧠 MLOps MCP (`mlops_mcp.py`)
Model registry management, metric tracking, and vector database provisioning.

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `register_model` | `model_name: str, version: str, metrics: dict, artifact_uri: str` | Registers a trained model version with metadata and evaluation scores. |
| `provision_vector_index` | `index_name: str, dimension: int = 1536, metric: str = "cosine"` | Provisions a pgvector or in-memory vector index with distance metric. |
| `log_training_run` | `run_id: str, epoch: int, loss: float, accuracy: float` | Logs training telemetry metrics to a centralized run tracker. |

---

## 3. 📊 AgentOps MCP (`agentops_mcp.py`)
Observability, tracing, and evaluation telemetry for multi-agent swarms.

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `trace_agent_span` | `agent_id: str, task_id: str, prompt_tokens: int, completion_tokens: int, latency_ms: float` | Records an OpenTelemetry/LangSmith compatible trace span. |
| `evaluate_agent_response` | `query: str, response: str, ground_truth: str = None` | Evaluates response semantic accuracy, hallucination risk, and schema adherence. |
| `get_token_finops_summary` | `start_date: str = None, end_date: str = None` | Calculates total token consumption and API costs across all active agents. |

---

## 4. 🗄️ DBOps MCP (`dbops_mcp.py`)
Safe database query execution, schema introspection, and migration verification.

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `inspect_schema` | `connection_string: str` | Extracts tables, columns, constraints, foreign keys, and indexes. |
| `execute_safe_query` | `query: str, read_only: bool = True, max_rows: int = 100` | Executes sandboxed read-only SQL queries with automatic `DROP`/`DELETE` blocking. |
| `verify_migrations` | `migrations_dir: str` | Inspects migration SQL files for destructive syntax (`DROP COLUMN`, unindexed foreign keys). |

---

## 5. 🐙 GitHub MCP (`github_mcp.py`)
Repository automation, PR reviews, issue management, and workflow dispatching.

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `create_pull_request` | `repo: str, branch: str, title: str, body: str` | Creates a GitHub PR with structured change descriptions and labels. |
| `list_open_issues` | `repo: str, label: str = None` | Retrieves open repository issues formatted for autonomous agent ingestion. |
| `post_pr_review_comment` | `repo: str, pr_number: int, commit_id: str, path: str, line: int, comment: str` | Submits targeted code review comments on specific PR diff lines. |

---

## 6. 🔐 Secrets MCP (`secrets_mcp.py`)
Zero-leak symmetric encryption and session secret vaulting.

| Tool Name | Arguments | Description |
| :--- | :--- | :--- |
| `set_secret` | `key_name: str, secret_value: str, ttl_days: int = 30` | Encrypts and stores secrets using Fernet symmetric encryption. |
| `get_secret` | `key_name: str` | Decrypts and retrieves secrets in-memory for authorized agent workers. |
| `rotate_secret` | `key_name: str, new_value: str` | Rotates encryption keys and updates secret timestamps. |
