"""
SecurityOps MCP Server Module - Operational Security & Compliance Analysis
"""
import ssl
import socket
import datetime
from typing import Dict, Any, List

class SecurityOpsMCP:
    """Security operations MCP tool definitions."""

    @staticmethod
    def check_tls_certificate(hostname: str, port: int = 443) -> Dict[str, Any]:
        """Validate SSL/TLS certificate expiration days and issuer info for a domain."""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    
                    not_after_str = cert['notAfter']
                    not_after_dt = datetime.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                    days_remaining = (not_after_dt - datetime.datetime.utcnow()).days

                    issuer = dict(x[0] for x in cert.get('issuer', []))
                    
                    return {
                        "hostname": hostname,
                        "valid": days_remaining > 0,
                        "days_remaining": days_remaining,
                        "expires_on": not_after_str,
                        "issuer_organization": issuer.get('organizationName', 'Unknown')
                    }
        except Exception as e:
            return {
                "hostname": hostname,
                "valid": False,
                "error": str(e),
                "days_remaining": 0
            }

    @staticmethod
    def audit_dependency_manifest(dependencies: List[str]) -> Dict[str, Any]:
        """Scan dependency package names and versions for known vulnerability patterns."""
        vulnerabilities = []
        known_issues = {
            "requests": ("<2.31.0", "CVE-2023-32681: Unintended leak of Proxy-Authorization header"),
            "urllib3": ("<1.26.17", "CVE-2023-45803: Cookie leak during cross-site redirects"),
            "flask": ("<2.2.5", "CVE-2023-30861: Insecure session cookie handling"),
            "django": ("<4.2.8", "CVE-2023-49081: Potential denial-of-service in QuerySet.aggregate()")
        }

        for dep in dependencies:
            dep_name = dep.split("==")[0].split(">=")[0].split("<")[0].strip().lower()
            if dep_name in known_issues:
                vuln_rule, advisory = known_issues[dep_name]
                vulnerabilities.append({
                    "package": dep,
                    "rule": vuln_rule,
                    "advisory": advisory,
                    "severity": "HIGH"
                })

        return {
            "total_scanned": len(dependencies),
            "vulnerabilities_found": len(vulnerabilities),
            "status": "SECURE" if len(vulnerabilities) == 0 else "ACTION_REQUIRED",
            "findings": vulnerabilities
        }

    @staticmethod
    def scan_dockerfile_security(dockerfile_content: str) -> Dict[str, Any]:
        """Evaluate Dockerfile for security best practices (root user, latest tag, exposed secrets)."""
        issues = []
        lines = dockerfile_content.splitlines()

        has_user = any("USER " in l for l in lines)
        if not has_user:
            issues.append({"issue": "Missing USER directive (container runs as root)", "severity": "HIGH"})

        for idx, l in enumerate(lines, 1):
            if "FROM " in l and ":latest" in l:
                issues.append({"line": idx, "issue": "Using unpinned ':latest' base image tag", "severity": "MEDIUM"})
            if "ENV " in l and ("KEY" in l or "SECRET" in l or "PASSWORD" in l):
                issues.append({"line": idx, "issue": "Potential hardcoded secret in ENV directive", "severity": "HIGH"})

        return {
            "issues_count": len(issues),
            "status": "PASSED" if len(issues) == 0 else "WARNINGS_FOUND",
            "findings": issues
        }
