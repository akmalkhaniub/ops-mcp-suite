"""
AgentOps MCP Server
====================
Production-grade MCP server providing agent observability, evaluation,
and prompt-management tools via the FastMCP framework.

Tools:
  - create_langsmith_project   [SIMULATED]  Create a LangSmith tracing project.
  - run_eval_harness           [SIMULATED]  Trigger an LLM-as-a-judge evaluation.
  - log_agent_trace            [REAL]       Append structured traces to a JSONL file.
  - get_trace_summary          [REAL]       Compute summary statistics from traces.
  - create_prompt_template     [REAL]       Store versioned prompt templates.
  - list_prompt_versions       [REAL]       List all versions of a prompt template.
"""

from __future__ import annotations

import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("agentops_mcp")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRACE_FILE = Path("./agent_traces.jsonl")
PROMPT_REGISTRY_FILE = Path("./prompt_registry.json")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP("AgentOps Tools")


# ===========================  HELPER FUNCTIONS  ============================


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load and return a JSON file as a dict; return empty dict if missing."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read %s: %s", path, exc)
        raise


def _save_json_file(path: Path, data: dict[str, Any]) -> None:
    """Atomically write *data* as JSON to *path*."""
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        tmp_path.replace(path)
    except OSError as exc:
        logger.error("Failed to write %s: %s", path, exc)
        if tmp_path.exists():
            tmp_path.unlink()
        raise


# ==============================  TOOLS  ====================================


@mcp.tool()
def create_langsmith_project(project_name: str, description: str = "") -> str:
    """[SIMULATED] Create a new LangSmith tracing project.

    Returns the environment variables required to route traces to the project.

    Args:
        project_name: Human-readable project name (e.g. ``my-chatbot-v2``).
        description:  Optional one-line description of the project.

    Returns:
        A multi-line string with the env-var block and a mock API key.
    """
    if not project_name or not project_name.strip():
        logger.warning("create_langsmith_project called with empty project_name")
        return "Error: project_name must be a non-empty string."

    project_name = project_name.strip()
    mock_api_key = f"ls_api_{uuid.uuid4().hex}"
    project_id = str(uuid.uuid4())

    logger.info("[SIMULATED] Created LangSmith project '%s' (id=%s)", project_name, project_id)

    lines = [
        f"[SIMULATED] Successfully created LangSmith project '{project_name}'.",
        f"Project ID  : {project_id}",
    ]
    if description:
        lines.append(f"Description : {description}")
    lines += [
        "",
        "Set the following environment variables:",
        f"  LANGCHAIN_TRACING_V2=true",
        f"  LANGCHAIN_PROJECT={project_name}",
        f"  LANGCHAIN_API_KEY={mock_api_key}",
    ]
    return "\n".join(lines)


@mcp.tool()
def run_eval_harness(
    dataset_name: str,
    agent_endpoint: str,
    judge_model: str = "gpt-4o",
    scoring_rubric: str = "accuracy,relevance,coherence",
) -> str:
    """[SIMULATED] Trigger an LLM-as-a-judge evaluation harness.

    Evaluates an agent against every example in the given dataset using the
    specified judge model and scoring rubric.

    Args:
        dataset_name:    Name of the evaluation dataset.
        agent_endpoint:  URL of the agent under test.
        judge_model:     LLM used for judging (default ``gpt-4o``).
        scoring_rubric:  Comma-separated scoring dimensions.

    Returns:
        Evaluation metadata: eval ID, example count, estimated completion time.
    """
    if not dataset_name or not dataset_name.strip():
        return "Error: dataset_name must be a non-empty string."
    if not agent_endpoint or not agent_endpoint.strip():
        return "Error: agent_endpoint must be a non-empty string."

    eval_id = f"eval-{uuid.uuid4().hex[:8]}"
    num_examples = random.randint(50, 500)
    est_minutes = round(num_examples * 0.12, 1)  # ~7 s per example
    rubric_dims = [d.strip() for d in scoring_rubric.split(",") if d.strip()]

    logger.info(
        "[SIMULATED] Eval '%s' started — dataset=%s, endpoint=%s, judge=%s",
        eval_id,
        dataset_name,
        agent_endpoint,
        judge_model,
    )

    return "\n".join([
        f"[SIMULATED] Evaluation launched successfully.",
        f"  Eval ID           : {eval_id}",
        f"  Dataset           : {dataset_name}",
        f"  Agent endpoint    : {agent_endpoint}",
        f"  Judge model       : {judge_model}",
        f"  Scoring rubric    : {', '.join(rubric_dims)}",
        f"  Number of examples: {num_examples}",
        f"  Est. completion   : ~{est_minutes} minutes",
    ])


@mcp.tool()
def log_agent_trace(
    agent_name: str,
    input_text: str,
    output_text: str,
    latency_ms: float,
    token_count: int,
) -> str:
    """Log a structured agent trace to ``./agent_traces.jsonl``.

    Each call appends a single JSON line capturing the agent invocation.

    Args:
        agent_name:  Identifier of the agent (e.g. ``support-bot``).
        input_text:  The user input / prompt sent to the agent.
        output_text: The agent's response.
        latency_ms:  End-to-end latency in milliseconds.
        token_count: Total tokens consumed (prompt + completion).

    Returns:
        Confirmation with the generated trace ID.
    """
    if not agent_name or not agent_name.strip():
        return "Error: agent_name must be a non-empty string."
    if latency_ms < 0:
        return "Error: latency_ms must be non-negative."
    if token_count < 0:
        return "Error: token_count must be non-negative."

    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    record = {
        "trace_id": trace_id,
        "agent_name": agent_name.strip(),
        "input": input_text,
        "output": output_text,
        "latency_ms": round(latency_ms, 2),
        "token_count": token_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": True,
    }

    try:
        with open(TRACE_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Logged trace %s for agent '%s'", trace_id, agent_name)
    except OSError as exc:
        logger.error("Failed to write trace: %s", exc)
        return f"Error: could not write trace — {exc}"

    return f"Trace logged successfully.\n  Trace ID : {trace_id}\n  File     : {TRACE_FILE.resolve()}"


@mcp.tool()
def get_trace_summary(agent_name: str = "") -> str:
    """Compute summary statistics from ``./agent_traces.jsonl``.

    Optionally filter by *agent_name*; if omitted, all traces are included.

    Args:
        agent_name: Filter to a specific agent. Leave empty for all agents.

    Returns:
        A formatted summary: total traces, average latency, average tokens,
        success rate, and per-agent breakdown.
    """
    if not TRACE_FILE.exists():
        return "No trace file found. Log some traces first with log_agent_trace."

    traces: list[dict[str, Any]] = []
    try:
        with open(TRACE_FILE, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed line %d in %s", lineno, TRACE_FILE)
    except OSError as exc:
        logger.error("Failed to read trace file: %s", exc)
        return f"Error: could not read trace file — {exc}"

    if agent_name:
        agent_name = agent_name.strip()
        traces = [t for t in traces if t.get("agent_name") == agent_name]

    if not traces:
        qualifier = f" for agent '{agent_name}'" if agent_name else ""
        return f"No traces found{qualifier}."

    total = len(traces)
    avg_latency = sum(t.get("latency_ms", 0) for t in traces) / total
    avg_tokens = sum(t.get("token_count", 0) for t in traces) / total
    successes = sum(1 for t in traces if t.get("success", False))
    success_rate = (successes / total) * 100

    # Per-agent breakdown
    agents: dict[str, int] = {}
    for t in traces:
        name = t.get("agent_name", "unknown")
        agents[name] = agents.get(name, 0) + 1

    lines = [
        "=== Trace Summary ===",
    ]
    if agent_name:
        lines.append(f"  Filter         : agent_name = '{agent_name}'")
    lines += [
        f"  Total traces   : {total}",
        f"  Avg latency    : {avg_latency:.1f} ms",
        f"  Avg tokens     : {avg_tokens:.0f}",
        f"  Success rate   : {success_rate:.1f}%",
        "",
        "  Per-agent counts:",
    ]
    for name, count in sorted(agents.items()):
        lines.append(f"    {name}: {count}")

    logger.info("Generated trace summary — %d traces", total)
    return "\n".join(lines)


@mcp.tool()
def create_prompt_template(
    template_name: str,
    template_text: str,
    version: str = "1.0",
) -> str:
    """Store a versioned prompt template in ``./prompt_registry.json``.

    Templates are indexed by name; each name can hold multiple versions.
    If the exact version already exists it will be overwritten.

    Args:
        template_name: Unique template identifier (e.g. ``summariser-v1``).
        template_text: The prompt template body (may contain ``{placeholders}``).
        version:       Semantic version string (default ``1.0``).

    Returns:
        Confirmation with template name, version, and storage path.
    """
    if not template_name or not template_name.strip():
        return "Error: template_name must be a non-empty string."
    if not template_text:
        return "Error: template_text must be a non-empty string."

    template_name = template_name.strip()
    version = version.strip() if version else "1.0"

    try:
        registry = _load_json_file(PROMPT_REGISTRY_FILE)
    except Exception as exc:
        return f"Error: could not load prompt registry — {exc}"

    if template_name not in registry:
        registry[template_name] = {}

    registry[template_name][version] = {
        "template_text": template_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        _save_json_file(PROMPT_REGISTRY_FILE, registry)
    except Exception as exc:
        return f"Error: could not save prompt registry — {exc}"

    total_versions = len(registry[template_name])
    logger.info("Saved prompt template '%s' v%s (%d version(s))", template_name, version, total_versions)

    return "\n".join([
        f"Prompt template saved successfully.",
        f"  Name           : {template_name}",
        f"  Version        : {version}",
        f"  Total versions : {total_versions}",
        f"  Registry file  : {PROMPT_REGISTRY_FILE.resolve()}",
    ])


@mcp.tool()
def list_prompt_versions(template_name: str) -> str:
    """List all stored versions of a prompt template from ``./prompt_registry.json``.

    Args:
        template_name: The template identifier to look up.

    Returns:
        A formatted list of versions with creation timestamps and a preview
        of the template text (first 80 characters).
    """
    if not template_name or not template_name.strip():
        return "Error: template_name must be a non-empty string."

    template_name = template_name.strip()

    try:
        registry = _load_json_file(PROMPT_REGISTRY_FILE)
    except Exception as exc:
        return f"Error: could not load prompt registry — {exc}"

    if template_name not in registry:
        return f"No template found with name '{template_name}'."

    versions = registry[template_name]
    if not versions:
        return f"Template '{template_name}' exists but has no versions."

    lines = [
        f"=== Prompt Template: {template_name} ===",
        f"  Total versions: {len(versions)}",
        "",
    ]
    for ver in sorted(versions.keys()):
        entry = versions[ver]
        created = entry.get("created_at", "unknown")
        text_preview = entry.get("template_text", "")[:80]
        if len(entry.get("template_text", "")) > 80:
            text_preview += "…"
        lines.append(f"  v{ver}  ({created})")
        lines.append(f"    Preview: {text_preview}")

    logger.info("Listed %d version(s) for template '%s'", len(versions), template_name)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
