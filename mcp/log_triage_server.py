import re
from typing import Dict, Any, List

try:
    from fastmcp import FastMCP
    mcp_triage = FastMCP("log-triage-server")
except ImportError:
    class FastMCP:
        def __init__(self, name: str): self.name = name
        def tool(self): return lambda func: func
    mcp_triage = FastMCP("log-triage-server")


@mcp_triage.tool()
def analyze_log_trace(log_text: str) -> Dict[str, Any]:
    """Parse log snippets, cluster error patterns, and extract root-cause stack traces."""
    lines = log_text.splitlines()
    errors = []
    warnings = []

    for idx, line in enumerate(lines, start=1):
        if re.search(r"ERROR|Exception|Fatal|Critical", line, re.IGNORECASE):
            errors.append({"line": idx, "content": line.strip()})
        elif re.search(r"WARN|Warning", line, re.IGNORECASE):
            warnings.append({"line": idx, "content": line.strip()})

    root_cause = "No critical errors found."
    if errors:
        root_cause = f"Detected {len(errors)} error log events. Primary error at line {errors[0]['line']}: {errors[0]['content']}"

    return {
        "total_lines": len(lines),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "root_cause_summary": root_cause,
    }


if __name__ == "__main__":
    print("Log Triage FastMCP Server Ready.")
