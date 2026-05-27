"""
GitHub MCP Server — Production-grade Model Context Protocol server for GitHub.

Provides tools to interact with the GitHub REST API: listing repos, inspecting
repo metadata, managing pull requests and issues, searching code, and fetching
file contents.  When no GITHUB_TOKEN is available, every tool returns realistic
[SIMULATED] mock data so the server remains functional for development/testing.

Environment variables:
    GITHUB_TOKEN  — GitHub Personal Access Token (PAT) for authenticated requests.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("github_mcp")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP("GitHub MCP Server")

# ---------------------------------------------------------------------------
# Constants / Configuration
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
GITHUB_TOKEN: str | None = os.environ.get("GITHUB_TOKEN")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    """Build request headers, including auth when a token is present."""
    hdrs: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        hdrs["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return hdrs


def _is_simulated() -> bool:
    """Return True when running without a real GitHub token."""
    return not GITHUB_TOKEN


def _handle_response(resp: requests.Response) -> dict[str, Any] | list[Any]:
    """Raise informative errors for common HTTP failure codes."""
    if resp.status_code == 200 or resp.status_code == 201:
        return resp.json()
    if resp.status_code == 401:
        raise PermissionError(
            "GitHub API returned 401 Unauthorized. "
            "Check that GITHUB_TOKEN is set and valid."
        )
    if resp.status_code == 403:
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset_ts = resp.headers.get("X-RateLimit-Reset", "")
        reset_str = ""
        if reset_ts:
            try:
                reset_dt = datetime.fromtimestamp(int(reset_ts), tz=timezone.utc)
                reset_str = f" Resets at {reset_dt.isoformat()}."
            except (ValueError, OSError):
                pass
        raise PermissionError(
            f"GitHub API returned 403 Forbidden (remaining={remaining}).{reset_str} "
            "You may be rate-limited or lack permissions."
        )
    if resp.status_code == 404:
        raise FileNotFoundError(
            f"GitHub API returned 404 Not Found for {resp.url}."
        )
    if resp.status_code == 422:
        detail = resp.json().get("message", resp.text)
        raise ValueError(f"GitHub API returned 422 Unprocessable Entity: {detail}")
    resp.raise_for_status()
    return resp.json()


def _fmt_repo(r: dict[str, Any]) -> str:
    """Format a single repo dict into a readable line."""
    return (
        f"• {r.get('full_name', r.get('name', '?'))}  "
        f"⭐ {r.get('stargazers_count', 0)}  "
        f"lang={r.get('language', 'N/A')}  "
        f"pushed={r.get('pushed_at', 'N/A')}  "
        f"vis={r.get('visibility', 'public')}"
    )


# ===================================================================
# Simulated (mock) data
# ===================================================================

_MOCK_REPOS: list[dict[str, Any]] = [
    {
        "full_name": "octocat/Hello-World",
        "name": "Hello-World",
        "stargazers_count": 2345,
        "language": "Python",
        "pushed_at": "2026-05-20T14:30:00Z",
        "visibility": "public",
        "description": "My first repository on GitHub!",
        "forks_count": 412,
        "open_issues_count": 17,
        "default_branch": "main",
        "license": {"spdx_id": "MIT"},
        "created_at": "2020-01-15T09:00:00Z",
        "size": 1024,
    },
    {
        "full_name": "octocat/Spoon-Knife",
        "name": "Spoon-Knife",
        "stargazers_count": 12045,
        "language": "HTML",
        "pushed_at": "2026-05-18T08:12:00Z",
        "visibility": "public",
        "description": "This repo is for trying out forking.",
        "forks_count": 138000,
        "open_issues_count": 0,
        "default_branch": "main",
        "license": {"spdx_id": "Apache-2.0"},
        "created_at": "2011-01-27T19:30:00Z",
        "size": 512,
    },
    {
        "full_name": "octocat/linguist",
        "name": "linguist",
        "stargazers_count": 890,
        "language": "Ruby",
        "pushed_at": "2026-05-21T22:45:00Z",
        "visibility": "public",
        "description": "Language savant.",
        "forks_count": 340,
        "open_issues_count": 42,
        "default_branch": "master",
        "license": {"spdx_id": "MIT"},
        "created_at": "2013-06-10T11:15:00Z",
        "size": 8192,
    },
]

_MOCK_PRS: list[dict[str, Any]] = [
    {
        "number": 42,
        "title": "Add dark-mode support",
        "user": {"login": "alice"},
        "created_at": "2026-05-19T10:00:00Z",
        "labels": [{"name": "enhancement"}, {"name": "ui"}],
        "requested_reviewers": [{"login": "bob"}],
        "state": "open",
    },
    {
        "number": 38,
        "title": "Fix off-by-one in pagination",
        "user": {"login": "bob"},
        "created_at": "2026-05-15T14:32:00Z",
        "labels": [{"name": "bug"}],
        "requested_reviewers": [],
        "state": "open",
    },
]

_MOCK_SEARCH_CODE: list[dict[str, Any]] = [
    {
        "name": "config.py",
        "path": "src/config.py",
        "repository": {"full_name": "octocat/Hello-World"},
        "text_matches": [{"fragment": "DATABASE_URL = os.environ.get('DATABASE_URL')"}],
    },
    {
        "name": "settings.py",
        "path": "app/settings.py",
        "repository": {"full_name": "octocat/Spoon-Knife"},
        "text_matches": [{"fragment": "DEBUG = False  # production setting"}],
    },
]


# ===================================================================
# Tools
# ===================================================================

@mcp.tool()
def list_repos(username: str = "", org: str = "") -> str:
    """List GitHub repositories for a user or organisation.

    If *username* is empty and no *org* is given, the authenticated user's
    repos are returned.  Results include name, stars, language, last push
    date, and visibility.

    Args:
        username: GitHub username whose repos to list. Empty -> authenticated user.
        org: GitHub organisation. Takes precedence over *username* when set.

    Returns:
        A formatted list of repositories or an error message.
    """
    if _is_simulated():
        logger.info("[SIMULATED] list_repos called")
        lines = ["[SIMULATED] GitHub Repositories:"]
        for r in _MOCK_REPOS:
            lines.append(_fmt_repo(r))
        return "\n".join(lines)

    try:
        if org:
            url = f"{GITHUB_API}/orgs/{org}/repos"
        elif username:
            url = f"{GITHUB_API}/users/{username}/repos"
        else:
            url = f"{GITHUB_API}/user/repos"

        resp = requests.get(url, headers=_headers(), params={"per_page": 30, "sort": "pushed"}, timeout=15)
        repos = _handle_response(resp)

        if not repos:
            return "No repositories found."

        lines = [f"Repositories ({len(repos)} shown):"]
        for r in repos:
            lines.append(_fmt_repo(r))
        return "\n".join(lines)

    except (PermissionError, FileNotFoundError, ValueError) as exc:
        logger.error("list_repos error: %s", exc)
        return f"Error: {exc}"
    except requests.RequestException as exc:
        logger.error("list_repos network error: %s", exc)
        return f"Network error: {exc}"


@mcp.tool()
def get_repo_info(owner: str, repo: str) -> str:
    """Get detailed metadata for a GitHub repository.

    Returns description, stars, forks, open issues, default branch, license,
    creation date, and repository size.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.

    Returns:
        Formatted repository details or an error message.
    """
    if not owner or not repo:
        return "Error: Both 'owner' and 'repo' are required."

    if _is_simulated():
        logger.info("[SIMULATED] get_repo_info called for %s/%s", owner, repo)
        r = _MOCK_REPOS[0]
        return (
            f"[SIMULATED] Repository: {owner}/{repo}\n"
            f"  Description : {r['description']}\n"
            f"  Stars       : {r['stargazers_count']}\n"
            f"  Forks       : {r['forks_count']}\n"
            f"  Open Issues : {r['open_issues_count']}\n"
            f"  Default Br. : {r['default_branch']}\n"
            f"  License     : {r['license']['spdx_id']}\n"
            f"  Created     : {r['created_at']}\n"
            f"  Size (KB)   : {r['size']}"
        )

    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}"
        resp = requests.get(url, headers=_headers(), timeout=15)
        r = _handle_response(resp)

        license_name = "N/A"
        if r.get("license"):
            license_name = r["license"].get("spdx_id") or r["license"].get("name", "N/A")

        return (
            f"Repository: {r.get('full_name', f'{owner}/{repo}')}\n"
            f"  Description : {r.get('description', 'N/A')}\n"
            f"  Stars       : {r.get('stargazers_count', 0)}\n"
            f"  Forks       : {r.get('forks_count', 0)}\n"
            f"  Open Issues : {r.get('open_issues_count', 0)}\n"
            f"  Default Br. : {r.get('default_branch', 'main')}\n"
            f"  License     : {license_name}\n"
            f"  Created     : {r.get('created_at', 'N/A')}\n"
            f"  Size (KB)   : {r.get('size', 0)}"
        )

    except (PermissionError, FileNotFoundError, ValueError) as exc:
        logger.error("get_repo_info error: %s", exc)
        return f"Error: {exc}"
    except requests.RequestException as exc:
        logger.error("get_repo_info network error: %s", exc)
        return f"Network error: {exc}"


@mcp.tool()
def list_pull_requests(owner: str, repo: str, state: str = "open") -> str:
    """List pull requests for a repository.

    Returns PR title, author, creation date, labels, and review status.

    Args:
        owner: Repository owner.
        repo: Repository name.
        state: PR state filter — 'open', 'closed', or 'all'. Defaults to 'open'.

    Returns:
        Formatted list of pull requests or an error message.
    """
    if not owner or not repo:
        return "Error: Both 'owner' and 'repo' are required."

    valid_states = {"open", "closed", "all"}
    if state not in valid_states:
        return f"Error: 'state' must be one of {valid_states}."

    if _is_simulated():
        logger.info("[SIMULATED] list_pull_requests for %s/%s (state=%s)", owner, repo, state)
        lines = [f"[SIMULATED] Pull Requests for {owner}/{repo} (state={state}):"]
        for pr in _MOCK_PRS:
            labels = ", ".join(lb["name"] for lb in pr.get("labels", []))
            reviewers = ", ".join(rv["login"] for rv in pr.get("requested_reviewers", []))
            lines.append(
                f"  #{pr['number']} {pr['title']}\n"
                f"    Author: {pr['user']['login']}  Created: {pr['created_at']}\n"
                f"    Labels: {labels or 'none'}  Reviewers: {reviewers or 'none'}"
            )
        return "\n".join(lines)

    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
        resp = requests.get(
            url,
            headers=_headers(),
            params={"state": state, "per_page": 30},
            timeout=15,
        )
        prs = _handle_response(resp)

        if not prs:
            return f"No pull requests with state='{state}' found for {owner}/{repo}."

        lines = [f"Pull Requests for {owner}/{repo} (state={state}, {len(prs)} shown):"]
        for pr in prs:
            labels = ", ".join(lb["name"] for lb in pr.get("labels", []))
            reviewers = ", ".join(rv["login"] for rv in pr.get("requested_reviewers", []))
            lines.append(
                f"  #{pr['number']} {pr['title']}\n"
                f"    Author: {pr['user']['login']}  Created: {pr['created_at']}\n"
                f"    Labels: {labels or 'none'}  Reviewers: {reviewers or 'none'}"
            )
        return "\n".join(lines)

    except (PermissionError, FileNotFoundError, ValueError) as exc:
        logger.error("list_pull_requests error: %s", exc)
        return f"Error: {exc}"
    except requests.RequestException as exc:
        logger.error("list_pull_requests network error: %s", exc)
        return f"Network error: {exc}"


@mcp.tool()
def create_issue(
    owner: str,
    repo: str,
    title: str,
    body: str = "",
    labels: str = "",
) -> str:
    """Create a new issue in a GitHub repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        title: Issue title (required).
        body: Issue body / description.
        labels: Comma-separated label names (e.g. 'bug,urgent').

    Returns:
        The URL of the newly created issue, or an error message.
    """
    if not owner or not repo:
        return "Error: Both 'owner' and 'repo' are required."
    if not title.strip():
        return "Error: 'title' cannot be empty."

    label_list = [lb.strip() for lb in labels.split(",") if lb.strip()] if labels else []

    if _is_simulated():
        logger.info("[SIMULATED] create_issue for %s/%s: %s", owner, repo, title)
        return (
            f"[SIMULATED] Issue created successfully.\n"
            f"  Title : {title}\n"
            f"  Labels: {', '.join(label_list) or 'none'}\n"
            f"  URL   : https://github.com/{owner}/{repo}/issues/99"
        )

    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = body
        if label_list:
            payload["labels"] = label_list

        resp = requests.post(url, headers=_headers(), json=payload, timeout=15)
        issue = _handle_response(resp)

        return (
            f"Issue created successfully.\n"
            f"  Title : {issue.get('title')}\n"
            f"  Number: #{issue.get('number')}\n"
            f"  URL   : {issue.get('html_url')}"
        )

    except (PermissionError, FileNotFoundError, ValueError) as exc:
        logger.error("create_issue error: %s", exc)
        return f"Error: {exc}"
    except requests.RequestException as exc:
        logger.error("create_issue network error: %s", exc)
        return f"Network error: {exc}"


@mcp.tool()
def search_code(query: str, owner: str = "", repo: str = "") -> str:
    """Search for code across GitHub repositories.

    Results include the file path, repository, and a snippet of matching
    content.  Optionally scope the search to a specific owner or repo.

    Args:
        query: Search query string (required).
        owner: Limit search to repos owned by this user/org.
        repo: Limit search to a specific repo (format: 'owner/repo' or just 'repo'
               when *owner* is also provided).

    Returns:
        Formatted search results or an error message.
    """
    if not query.strip():
        return "Error: 'query' cannot be empty."

    if _is_simulated():
        logger.info("[SIMULATED] search_code for query=%r", query)
        lines = [f"[SIMULATED] Code search results for '{query}':"]
        for item in _MOCK_SEARCH_CODE:
            snippet = item["text_matches"][0]["fragment"] if item.get("text_matches") else ""
            lines.append(
                f"  {item['repository']['full_name']} / {item['path']}\n"
                f"    Snippet: {snippet}"
            )
        return "\n".join(lines)

    try:
        q_parts = [query]
        if owner and repo:
            # If repo doesn't already include owner, prepend it
            full_repo = repo if "/" in repo else f"{owner}/{repo}"
            q_parts.append(f"repo:{full_repo}")
        elif owner:
            q_parts.append(f"user:{owner}")
        elif repo and "/" in repo:
            q_parts.append(f"repo:{repo}")

        url = f"{GITHUB_API}/search/code"
        # text-match media type for snippets
        headers = _headers()
        headers["Accept"] = "application/vnd.github.text-match+json"

        resp = requests.get(
            url,
            headers=headers,
            params={"q": " ".join(q_parts), "per_page": 15},
            timeout=20,
        )
        data = _handle_response(resp)

        items = data.get("items", [])
        if not items:
            return f"No code results found for '{query}'."

        lines = [f"Code search results ({data.get('total_count', '?')} total, showing {len(items)}):"]
        for item in items:
            snippet = ""
            if item.get("text_matches"):
                snippet = item["text_matches"][0].get("fragment", "")[:200]
            lines.append(
                f"  {item['repository']['full_name']} / {item['path']}\n"
                f"    Snippet: {snippet or '(no preview)'}"
            )
        return "\n".join(lines)

    except (PermissionError, FileNotFoundError, ValueError) as exc:
        logger.error("search_code error: %s", exc)
        return f"Error: {exc}"
    except requests.RequestException as exc:
        logger.error("search_code network error: %s", exc)
        return f"Network error: {exc}"


@mcp.tool()
def get_file_contents(
    owner: str,
    repo: str,
    path: str,
    branch: str = "main",
) -> str:
    """Retrieve and decode the contents of a file from a GitHub repository.

    The GitHub Contents API returns base64-encoded content; this tool
    transparently decodes it and returns the plain-text result.

    Args:
        owner: Repository owner.
        repo: Repository name.
        path: File path within the repository (e.g. 'src/main.py').
        branch: Branch or ref to read from. Defaults to 'main'.

    Returns:
        The decoded file content or an error message.
    """
    if not owner or not repo:
        return "Error: Both 'owner' and 'repo' are required."
    if not path.strip():
        return "Error: 'path' cannot be empty."

    if _is_simulated():
        logger.info("[SIMULATED] get_file_contents for %s/%s:%s@%s", owner, repo, path, branch)
        return (
            f"[SIMULATED] File: {owner}/{repo}/{path} (branch={branch})\n"
            f"--- content ---\n"
            f"# {path}\n"
            f"# This is simulated file content.\n\n"
            f'print("Hello from {repo}!")\n'
            f"--- end ---"
        )

    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        resp = requests.get(
            url,
            headers=_headers(),
            params={"ref": branch},
            timeout=15,
        )
        data = _handle_response(resp)

        if isinstance(data, list):
            # The path is a directory — list entries instead
            entries = [f"  {'📁' if e['type'] == 'dir' else '📄'} {e['name']}" for e in data]
            return f"Path '{path}' is a directory with {len(entries)} entries:\n" + "\n".join(entries)

        encoding = data.get("encoding", "")
        if encoding == "base64":
            raw = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        else:
            raw = data.get("content", "(unable to decode)")

        size = data.get("size", 0)
        sha = data.get("sha", "?")[:8]

        return (
            f"File: {owner}/{repo}/{path} (branch={branch}, size={size}B, sha={sha})\n"
            f"--- content ---\n{raw}\n--- end ---"
        )

    except (PermissionError, FileNotFoundError, ValueError) as exc:
        logger.error("get_file_contents error: %s", exc)
        return f"Error: {exc}"
    except requests.RequestException as exc:
        logger.error("get_file_contents network error: %s", exc)
        return f"Network error: {exc}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting GitHub MCP Server (token=%s)", "present" if GITHUB_TOKEN else "MISSING — simulated mode")
    mcp.run()
