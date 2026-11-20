"""
SecurityOps MCP Server Module - Operational Security & Compliance Analysis
"""
import datetime
import ipaddress
import re
import ssl
import socket
from typing import Dict, Any, List, Tuple


def _check_ip_public(raw_ip: str, original_host: str) -> None:
    """Raise ValueError if an IP address is private, loopback, link-local, reserved, multicast, or unspecified."""
    ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
    target = getattr(ip, "ipv4_mapped", None) or ip
    if (
        target.is_private
        or target.is_loopback
        or target.is_link_local
        or target.is_reserved
        or target.is_multicast
        or target.is_unspecified
    ):
        raise ValueError(f"SSRF blocked: non-public IP '{original_host}' ({raw_ip}) is forbidden.")


def _validate_public_hostname(hostname: str) -> None:
    """Block SSRF against loopback, private RFC1918, and cloud metadata IPs/hostnames."""
    host = hostname.strip().lower().rstrip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if (
        not host
        or host in {"localhost", "ip6-localhost", "metadata.google.internal", "metadata.azure.com"}
        or host.endswith(".localhost")
    ):
        raise ValueError(f"SSRF blocked: '{hostname}' is a restricted internal host.")
    try:
        _check_ip_public(host, hostname)
        return
    except ValueError as exc:
        if "SSRF blocked" in str(exc):
            raise

    try:
        addr_info = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return

    for _family, _type, _proto, _canonname, sockaddr in addr_info:
        if sockaddr and sockaddr[0]:
            _check_ip_public(sockaddr[0], hostname)


def _parse_version_tuple(version_str: str) -> Tuple[int, ...] | None:
    """Extract numeric version tuple for comparison (e.g., '2.31.0' -> (2, 31, 0))."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", version_str)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _is_version_vulnerable(spec: str, max_safe_exclusive: str) -> bool:
    """Return True when dependency spec is unpinned or specifies a version below max_safe_exclusive."""
    threshold = _parse_version_tuple(max_safe_exclusive)
    if threshold is None:
        return True
    match = re.search(r"(===|==|~=|>=|<=|!=|>|<)\s*([^\s,;]+)", spec)
    if not match:
        return True
    op, ver_str = match.group(1), match.group(2)
    ver = _parse_version_tuple(ver_str)
    if ver is None:
        return True
    max_len = max(len(ver), len(threshold))
    ver_padded = ver + (0,) * (max_len - len(ver))
    thr_padded = threshold + (0,) * (max_len - len(threshold))
    if op in (">=", ">"):
        return ver_padded < thr_padded
    return ver_padded < thr_padded


class SecurityOpsMCP:
    """Security operations MCP tool definitions."""

    @staticmethod
    def check_tls_certificate(hostname: str, port: int = 443) -> Dict[str, Any]:
        """Validate SSL/TLS certificate expiration days and issuer info for a domain."""
        try:
            _validate_public_hostname(hostname)
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    
                    not_after_str = cert['notAfter']
                    not_after_dt = datetime.datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=datetime.timezone.utc)
                    days_remaining = (not_after_dt - datetime.datetime.now(datetime.timezone.utc)).days

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
            dep_name = re.split(r"[=<>~!;\[]", dep, maxsplit=1)[0].strip().lower()
            if dep_name in known_issues:
                vuln_rule, advisory = known_issues[dep_name]
                min_safe = vuln_rule.lstrip("<=")
                if _is_version_vulnerable(dep, min_safe):
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
