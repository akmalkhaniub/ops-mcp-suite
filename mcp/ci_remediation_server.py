from typing import Dict, Any

try:
    from fastmcp import FastMCP
    mcp_ci = FastMCP("ci-remediation-server")
except ImportError:
    class FastMCP:
        def __init__(self, name: str): self.name = name
        def tool(self): return lambda func: func
    mcp_ci = FastMCP("ci-remediation-server")


@mcp_ci.tool()
def diagnose_pipeline_failure(pipeline_name: str, build_log: str) -> Dict[str, Any]:
    """Diagnose CI/CD pipeline failure and output auto-fix git patch recommendations."""
    if "ModuleNotFoundError" in build_log:
        missing_pkg = build_log.split("No module named")[-1].strip().strip("'\"")
        patch = f"# REMEDIATION: Add missing package to requirements.txt\necho '{missing_pkg}' >> requirements.txt"
        diagnosis = f"Build failed due to missing Python package '{missing_pkg}'."
    elif "SyntaxError" in build_log:
        patch = "# REMEDIATION: Fix syntax error at highlighted line before committing."
        diagnosis = "Build failed due to code syntax error."
    else:
        patch = "# REMEDIATION: Re-run build after verifying environment variables."
        diagnosis = "Build failed due to test assertion failure or unhandled exception."

    return {
        "pipeline_name": pipeline_name,
        "diagnosis": diagnosis,
        "recommended_patch": patch,
    }


if __name__ == "__main__":
    print("CI Remediation FastMCP Server Ready.")
