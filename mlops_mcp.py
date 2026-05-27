"""
MLOps MCP Server — Production-grade toolset for model lifecycle
management including vector DB provisioning, fine-tuning, model
registry, promotion, metrics, and model comparison.

Requires: mcp[cli]
"""

from mcp.server.fastmcp import FastMCP
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP("MLOps Tools")

# ---------------------------------------------------------------------------
# Realistic mock data
# ---------------------------------------------------------------------------

_MODEL_REGISTRY: list[dict] = [
    {
        "name": "gpt-4o-mini-ft-support",
        "version": "3.2.1",
        "stage": "production",
        "metrics": {"accuracy": 0.934, "latency_p50_ms": 120, "latency_p95_ms": 245},
        "last_updated": "2026-05-18T09:32:00Z",
        "description": "Fine-tuned GPT-4o-mini for customer-support triage.",
    },
    {
        "name": "claude-3-haiku-ft-summariser",
        "version": "2.1.0",
        "stage": "staging",
        "metrics": {"accuracy": 0.912, "latency_p50_ms": 95, "latency_p95_ms": 198},
        "last_updated": "2026-05-20T14:15:00Z",
        "description": "Haiku fine-tune for document summarisation.",
    },
    {
        "name": "embedding-ada-002-custom",
        "version": "1.0.4",
        "stage": "production",
        "metrics": {"accuracy": 0.978, "latency_p50_ms": 18, "latency_p95_ms": 42},
        "last_updated": "2026-04-30T22:00:00Z",
        "description": "Custom embedding model trained on internal docs.",
    },
    {
        "name": "llama-3-70b-ft-codegen",
        "version": "4.0.0-rc1",
        "stage": "staging",
        "metrics": {"accuracy": 0.889, "latency_p50_ms": 340, "latency_p95_ms": 780},
        "last_updated": "2026-05-21T17:45:00Z",
        "description": "LLaMA-3 70B fine-tuned for code generation.",
    },
    {
        "name": "mistral-7b-ft-classifier",
        "version": "1.3.0",
        "stage": "archived",
        "metrics": {"accuracy": 0.865, "latency_p50_ms": 55, "latency_p95_ms": 130},
        "last_updated": "2026-03-12T08:20:00Z",
        "description": "Mistral-7B intent-classification model (deprecated).",
    },
]

_MODEL_METRICS: dict[str, dict] = {
    "gpt-4o-mini-ft-support": {
        "latency_p50_ms": 120,
        "latency_p95_ms": 245,
        "latency_p99_ms": 410,
        "tokens_per_sec": 85.3,
        "cost_per_1k_tokens_usd": 0.0045,
        "error_rate_pct": 0.12,
        "requests_last_24h": 148_320,
        "avg_input_tokens": 312,
        "avg_output_tokens": 187,
    },
    "claude-3-haiku-ft-summariser": {
        "latency_p50_ms": 95,
        "latency_p95_ms": 198,
        "latency_p99_ms": 355,
        "tokens_per_sec": 112.7,
        "cost_per_1k_tokens_usd": 0.0032,
        "error_rate_pct": 0.08,
        "requests_last_24h": 63_450,
        "avg_input_tokens": 1024,
        "avg_output_tokens": 256,
    },
    "embedding-ada-002-custom": {
        "latency_p50_ms": 18,
        "latency_p95_ms": 42,
        "latency_p99_ms": 78,
        "tokens_per_sec": 1450.0,
        "cost_per_1k_tokens_usd": 0.0001,
        "error_rate_pct": 0.01,
        "requests_last_24h": 1_230_500,
        "avg_input_tokens": 256,
        "avg_output_tokens": 0,
    },
    "llama-3-70b-ft-codegen": {
        "latency_p50_ms": 340,
        "latency_p95_ms": 780,
        "latency_p99_ms": 1250,
        "tokens_per_sec": 42.1,
        "cost_per_1k_tokens_usd": 0.0098,
        "error_rate_pct": 0.34,
        "requests_last_24h": 22_100,
        "avg_input_tokens": 580,
        "avg_output_tokens": 420,
    },
    "mistral-7b-ft-classifier": {
        "latency_p50_ms": 55,
        "latency_p95_ms": 130,
        "latency_p99_ms": 210,
        "tokens_per_sec": 195.0,
        "cost_per_1k_tokens_usd": 0.0008,
        "error_rate_pct": 0.05,
        "requests_last_24h": 0,
        "avg_input_tokens": 128,
        "avg_output_tokens": 12,
    },
}


# ===================================================================
# Tool 1 — Provision Vector DB
# ===================================================================

@mcp.tool()
def provision_vector_db(
    index_name: str,
    dimension: int = 1536,
    metric: str = "cosine",
) -> str:
    """
    [SIMULATED] Provisions a Pinecone-style vector database index.

    Args:
        index_name: Name for the new vector index.
        dimension: Embedding dimension (default 1536 for ada-002).
        metric: Distance metric — ``cosine``, ``euclidean``, or ``dotproduct``.

    Returns:
        Simulated provisioning result with API key and endpoint.
    """
    logger.info(
        "provision_vector_db called: index=%s dim=%d metric=%s",
        index_name, dimension, metric,
    )

    if not index_name:
        return "❌ 'index_name' is required."

    valid_metrics = {"cosine", "euclidean", "dotproduct"}
    if metric.lower() not in valid_metrics:
        return f"❌ Invalid metric '{metric}'. Must be one of: {', '.join(sorted(valid_metrics))}"

    if dimension < 1:
        return "❌ 'dimension' must be a positive integer."

    mock_api_key = f"pc-{uuid.uuid4().hex}"
    mock_endpoint = f"https://{index_name}-{uuid.uuid4().hex[:8]}.svc.us-west-2.pinecone.io"
    index_id = uuid.uuid4().hex[:12]

    return (
        f"[SIMULATED] ✅ Vector DB index provisioned.\n"
        f"   Index Name  : {index_name}\n"
        f"   Index ID    : {index_id}\n"
        f"   Dimension   : {dimension}\n"
        f"   Metric      : {metric}\n"
        f"   Replicas    : 1\n"
        f"   Shards      : 1\n"
        f"   Status      : Ready\n"
        f"\n"
        f"   PINECONE_API_KEY  = {mock_api_key}\n"
        f"   PINECONE_ENDPOINT = {mock_endpoint}\n"
        f"   PINECONE_ENV      = us-west-2"
    )


# ===================================================================
# Tool 2 — Trigger Fine-Tuning
# ===================================================================

@mcp.tool()
def trigger_fine_tuning(
    dataset_uri: str,
    base_model: str = "gpt-4o-mini",
    epochs: int = 3,
    learning_rate: float = 1e-5,
) -> str:
    """
    [SIMULATED] Triggers a fine-tuning job on a foundation model.

    Args:
        dataset_uri: URI of the training dataset
                     (e.g. ``s3://my-bucket/data/train.jsonl``).
        base_model: Foundation model to fine-tune (default ``gpt-4o-mini``).
        epochs: Number of training epochs (default 3).
        learning_rate: Learning rate (default 1e-5).

    Returns:
        Simulated job submission summary with job ID, estimated duration,
        and cost estimate.
    """
    logger.info(
        "trigger_fine_tuning called: dataset=%s model=%s epochs=%d lr=%s",
        dataset_uri, base_model, epochs, learning_rate,
    )

    if not dataset_uri:
        return "❌ 'dataset_uri' is required."
    if epochs < 1:
        return "❌ 'epochs' must be ≥ 1."
    if learning_rate <= 0:
        return "❌ 'learning_rate' must be a positive number."

    job_id = f"ft-job-{uuid.uuid4().hex[:12]}"
    estimated_minutes = epochs * 45  # ~45 min per epoch (mock)
    estimated_cost = round(epochs * 12.50, 2)  # ~$12.50 per epoch (mock)
    now = datetime.now(timezone.utc)
    eta = now + timedelta(minutes=estimated_minutes)

    return (
        f"[SIMULATED] ✅ Fine-tuning job submitted.\n"
        f"   Job ID         : {job_id}\n"
        f"   Base Model     : {base_model}\n"
        f"   Dataset        : {dataset_uri}\n"
        f"   Epochs         : {epochs}\n"
        f"   Learning Rate  : {learning_rate}\n"
        f"   Submitted At   : {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"   Est. Duration  : ~{estimated_minutes} minutes\n"
        f"   Est. Completion: {eta.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"   Est. Cost      : ${estimated_cost:.2f}\n"
        f"   Status         : queued -> training"
    )


# ===================================================================
# Tool 3 — List Model Registry
# ===================================================================

@mcp.tool()
def list_model_registry() -> str:
    """
    Returns the current model registry showing all registered models
    with their version, lifecycle stage, key metrics, and last-updated
    timestamp.

    Returns:
        A formatted table of all models in the registry.
    """
    logger.info("list_model_registry called.")

    header = (
        f"{'Model Name':<35} {'Version':<14} {'Stage':<12} "
        f"{'Accuracy':<10} {'p50 (ms)':<10} {'p95 (ms)':<10} {'Last Updated':<22}"
    )
    separator = "─" * len(header)

    lines = ["📋 Model Registry", separator, header, separator]

    for m in _MODEL_REGISTRY:
        metrics = m["metrics"]
        lines.append(
            f"{m['name']:<35} {m['version']:<14} {m['stage']:<12} "
            f"{metrics['accuracy']:<10.3f} {metrics['latency_p50_ms']:<10} "
            f"{metrics['latency_p95_ms']:<10} {m['last_updated']:<22}"
        )

    lines.append(separator)
    lines.append(f"Total models: {len(_MODEL_REGISTRY)}")
    return "\n".join(lines)


# ===================================================================
# Tool 4 — Promote Model
# ===================================================================

@mcp.tool()
def promote_model(
    model_name: str,
    from_stage: str = "staging",
    to_stage: str = "production",
) -> str:
    """
    [SIMULATED] Promotes a model from one lifecycle stage to another
    (e.g. staging -> production) and returns rollback instructions.

    Args:
        model_name: Name of the model to promote.
        from_stage: Current stage (default ``staging``).
        to_stage: Target stage (default ``production``).

    Returns:
        Promotion confirmation with rollback procedure.
    """
    logger.info(
        "promote_model called: model=%s from=%s to=%s",
        model_name, from_stage, to_stage,
    )

    if not model_name:
        return "❌ 'model_name' is required."

    valid_stages = {"staging", "production", "archived", "development"}
    if from_stage.lower() not in valid_stages:
        return f"❌ Invalid from_stage '{from_stage}'. Must be one of: {', '.join(sorted(valid_stages))}"
    if to_stage.lower() not in valid_stages:
        return f"❌ Invalid to_stage '{to_stage}'. Must be one of: {', '.join(sorted(valid_stages))}"
    if from_stage.lower() == to_stage.lower():
        return f"❌ from_stage and to_stage are both '{from_stage}' — nothing to do."

    # Check the model exists in our mock registry
    match = next((m for m in _MODEL_REGISTRY if m["name"] == model_name), None)
    if not match:
        known = ", ".join(m["name"] for m in _MODEL_REGISTRY)
        return f"❌ Model '{model_name}' not found in registry. Known models: {known}"

    if match["stage"].lower() != from_stage.lower():
        return (
            f"❌ Model '{model_name}' is currently in stage '{match['stage']}', "
            f"not '{from_stage}'."
        )

    promotion_id = f"promo-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return (
        f"[SIMULATED] ✅ Model promoted successfully.\n"
        f"   Model          : {model_name} v{match['version']}\n"
        f"   Transition     : {from_stage} -> {to_stage}\n"
        f"   Promotion ID   : {promotion_id}\n"
        f"   Timestamp      : {now}\n"
        f"\n"
        f"   🔄 Rollback instructions:\n"
        f"     1. Run: promote_model('{model_name}', from_stage='{to_stage}', to_stage='{from_stage}')\n"
        f"     2. Verify health: fetch_model_metrics('{model_name}')\n"
        f"     3. Notify on-call: #mlops-alerts channel\n"
        f"     4. Reference promotion ID: {promotion_id}"
    )


# ===================================================================
# Tool 5 — Fetch Model Metrics
# ===================================================================

@mcp.tool()
def fetch_model_metrics(model_name: str) -> str:
    """
    Returns realistic mock performance metrics for a registered model
    including latency percentiles, throughput, cost, and error rate.

    Args:
        model_name: Name of the model to query.

    Returns:
        Formatted metrics report.
    """
    logger.info("fetch_model_metrics called: model=%s", model_name)

    if not model_name:
        return "❌ 'model_name' is required."

    metrics = _MODEL_METRICS.get(model_name)
    if not metrics:
        known = ", ".join(_MODEL_METRICS.keys())
        return f"❌ No metrics found for '{model_name}'. Known models: {known}"

    return (
        f"📊 Metrics for '{model_name}'\n"
        f"{'─' * 45}\n"
        f"  Latency (p50)       : {metrics['latency_p50_ms']} ms\n"
        f"  Latency (p95)       : {metrics['latency_p95_ms']} ms\n"
        f"  Latency (p99)       : {metrics['latency_p99_ms']} ms\n"
        f"  Throughput          : {metrics['tokens_per_sec']} tokens/sec\n"
        f"  Cost / 1K tokens    : ${metrics['cost_per_1k_tokens_usd']}\n"
        f"  Error Rate          : {metrics['error_rate_pct']}%\n"
        f"  Requests (24h)      : {metrics['requests_last_24h']:,}\n"
        f"  Avg Input Tokens    : {metrics['avg_input_tokens']}\n"
        f"  Avg Output Tokens   : {metrics['avg_output_tokens']}"
    )


# ===================================================================
# Tool 6 — Compare Models
# ===================================================================

@mcp.tool()
def compare_models(model_a: str, model_b: str) -> str:
    """
    Returns a side-by-side comparison of two models' key performance
    metrics as a formatted table.

    Args:
        model_a: First model name.
        model_b: Second model name.

    Returns:
        Formatted comparison table with deltas.
    """
    logger.info("compare_models called: a=%s b=%s", model_a, model_b)

    if not model_a or not model_b:
        return "❌ Both 'model_a' and 'model_b' are required."

    ma = _MODEL_METRICS.get(model_a)
    mb = _MODEL_METRICS.get(model_b)

    errors: list[str] = []
    if not ma:
        errors.append(f"❌ No metrics for '{model_a}'.")
    if not mb:
        errors.append(f"❌ No metrics for '{model_b}'.")
    if errors:
        known = ", ".join(_MODEL_METRICS.keys())
        errors.append(f"Known models: {known}")
        return "\n".join(errors)

    # Build comparison rows
    def _fmt(val: float | int) -> str:
        if isinstance(val, float):
            if val < 0.01:
                return f"{val:.4f}"
            return f"{val:.2f}"
        return f"{val:,}"

    def _delta(a_val: float | int, b_val: float | int, lower_is_better: bool = True) -> str:
        diff = b_val - a_val
        if diff == 0:
            return "  ="
        arrow = "↓" if diff < 0 else "↑"
        better = (diff < 0) == lower_is_better
        indicator = "✅" if better else "⚠️"
        return f"{arrow} {abs(diff):.2f} {indicator}" if isinstance(diff, float) else f"{arrow} {abs(diff):,} {indicator}"

    rows = [
        ("Latency p50 (ms)",     "latency_p50_ms",         True),
        ("Latency p95 (ms)",     "latency_p95_ms",         True),
        ("Latency p99 (ms)",     "latency_p99_ms",         True),
        ("Tokens/sec",           "tokens_per_sec",         False),
        ("Cost/1K tokens ($)",   "cost_per_1k_tokens_usd", True),
        ("Error Rate (%)",       "error_rate_pct",         True),
        ("Requests (24h)",       "requests_last_24h",      False),
        ("Avg Input Tokens",     "avg_input_tokens",       False),
        ("Avg Output Tokens",    "avg_output_tokens",      False),
    ]

    col_w = max(len(model_a), len(model_b), 14)
    label_w = 22

    header = f"{'Metric':<{label_w}} {model_a:>{col_w}}   {model_b:>{col_w}}   {'Delta':>18}"
    sep = "─" * len(header)

    lines = [
        f"⚖️  Model Comparison: {model_a} vs {model_b}",
        sep,
        header,
        sep,
    ]

    for label, key, lower_better in rows:
        a_val = ma[key]
        b_val = mb[key]
        delta = _delta(a_val, b_val, lower_better)
        lines.append(
            f"{label:<{label_w}} {_fmt(a_val):>{col_w}}   {_fmt(b_val):>{col_w}}   {delta:>18}"
        )

    lines.append(sep)

    # Winner heuristic: lower error rate + lower p95 wins
    a_score = ma["latency_p95_ms"] + ma["error_rate_pct"] * 1000
    b_score = mb["latency_p95_ms"] + mb["error_rate_pct"] * 1000
    if a_score < b_score:
        winner = model_a
    elif b_score < a_score:
        winner = model_b
    else:
        winner = "Tie"

    lines.append(f"🏆 Suggested winner (latency + error heuristic): {winner}")
    return "\n".join(lines)


# ===================================================================
# Entrypoint
# ===================================================================

if __name__ == "__main__":
    mcp.run()
