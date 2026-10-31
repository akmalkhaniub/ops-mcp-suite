import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp.container_server import inspect_container_health, list_running_containers
from mcp.log_triage_server import analyze_log_trace
from mcp.ci_remediation_server import diagnose_pipeline_failure


def test_container_health_server():
    res = inspect_container_health("api-gateway")
    assert res["container_name"] == "api-gateway"
    assert res["status"] == "running"
    assert res["health"] == "healthy"

    containers = list_running_containers()
    assert len(containers) >= 3


def test_log_triage_server():
    log_data = "INFO: App starting\nERROR: Failed to connect to Redis on port 6379\nWARN: Low memory warning"
    analysis = analyze_log_trace(log_data)

    assert analysis["error_count"] == 1
    assert analysis["warning_count"] == 1
    assert "Redis" in analysis["root_cause_summary"]


def test_ci_remediation_server():
    build_log = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'fastapi'"
    diag = diagnose_pipeline_failure("github-actions-ci", build_log)

    assert "missing Python package 'fastapi'" in diag["diagnosis"]
    assert "fastapi" in diag["recommended_patch"]
