"""
DevOps MCP Server — Production-grade toolset for cloud infrastructure,
secrets management, IAM policy generation, container deployment, and
service health monitoring.

Requires: mcp[cli], boto3, requests
"""

from mcp.server.fastmcp import FastMCP
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP("DevOps Tools")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SECRETS_FILE = Path("./devops_secrets.json")


# ===================================================================
# Helper – secrets store I/O
# ===================================================================

def _load_secrets() -> dict:
    """Load the local JSON secrets store, creating it if absent."""
    if SECRETS_FILE.exists():
        try:
            return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt secrets file – reinitialising: %s", exc)
    return {}


def _save_secrets(data: dict) -> None:
    """Persist the secrets dict to the local JSON file."""
    SECRETS_FILE.write_text(
        json.dumps(data, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# ===================================================================
# Tool 1 — Provision S3 Bucket
# ===================================================================

@mcp.tool()
def provision_s3_bucket(
    bucket_name: str,
    region: str = "us-east-1",
    enable_versioning: bool = False,
    tags: str = "",
) -> str:
    """
    Provisions a new AWS S3 bucket with optional versioning and tagging.

    Falls back to a [SIMULATED] response when no AWS credentials are
    available, so the tool is always safe to call during development.

    Args:
        bucket_name: Globally unique S3 bucket name.
        region: AWS region (default ``us-east-1``).
        enable_versioning: Whether to enable bucket versioning.
        tags: Comma-separated ``Key=Value`` pairs, e.g.
              ``"Environment=dev,Team=platform"``.

    Returns:
        A human-readable summary of the provisioning result.
    """
    logger.info(
        "provision_s3_bucket called: bucket=%s region=%s versioning=%s tags=%s",
        bucket_name, region, enable_versioning, tags,
    )

    # --- Parse tags --------------------------------------------------------
    tag_set: list[dict[str, str]] = []
    if tags:
        for pair in tags.split(","):
            pair = pair.strip()
            if "=" not in pair:
                return f"❌ Invalid tag format '{pair}'. Expected Key=Value."
            k, v = pair.split("=", 1)
            tag_set.append({"Key": k.strip(), "Value": v.strip()})

    try:
        s3 = boto3.client("s3", region_name=region)

        # Create bucket
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        logger.info("Bucket '%s' created in %s.", bucket_name, region)

        # Versioning
        if enable_versioning:
            s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"},
            )
            logger.info("Versioning enabled on '%s'.", bucket_name)

        # Tagging
        if tag_set:
            s3.put_bucket_tagging(
                Bucket=bucket_name,
                Tagging={"TagSet": tag_set},
            )
            logger.info("Applied %d tag(s) to '%s'.", len(tag_set), bucket_name)

        lines = [
            f"✅ Successfully provisioned S3 bucket '{bucket_name}' in region '{region}'.",
            f"   Versioning : {'Enabled' if enable_versioning else 'Suspended'}",
        ]
        if tag_set:
            lines.append(f"   Tags       : {tag_set}")
        return "\n".join(lines)

    except NoCredentialsError:
        logger.warning("No AWS credentials – returning simulated response.")
        lines = [
            f"[SIMULATED] ✅ Provisioned S3 bucket '{bucket_name}' in '{region}'. (No AWS credentials found)",
            f"   Versioning : {'Enabled' if enable_versioning else 'Suspended'}",
        ]
        if tag_set:
            lines.append(f"   Tags       : {tag_set}")
        return "\n".join(lines)

    except ClientError as exc:
        logger.error("AWS ClientError: %s", exc)
        return f"❌ Failed to provision bucket: {exc}"

    except Exception as exc:
        logger.exception("Unexpected error in provision_s3_bucket")
        return f"❌ Unexpected error: {exc}"


# ===================================================================
# Tool 2 — Generate Bedrock Credentials
# ===================================================================

@mcp.tool()
def generate_bedrock_credentials(
    role_arn: str,
    session_duration: int = 3600,
) -> str:
    """
    Assumes an IAM role via STS and returns temporary credentials scoped
    for AWS Bedrock access.

    Falls back to [SIMULATED] credentials when no AWS credentials are
    configured.

    Args:
        role_arn: The ARN of the IAM role to assume
                  (e.g. ``arn:aws:iam::123456789012:role/BedrockRole``).
        session_duration: Session lifetime in seconds (900–43200, default 3600).

    Returns:
        Temporary AWS credentials or a simulated equivalent.
    """
    logger.info(
        "generate_bedrock_credentials called: role_arn=%s duration=%d",
        role_arn, session_duration,
    )

    if not role_arn.startswith("arn:aws:iam::") and not role_arn.startswith("arn:aws:iam:"):
        # Loose validation – let AWS reject truly invalid ARNs
        logger.warning("role_arn may be malformed: %s", role_arn)

    if not 900 <= session_duration <= 43200:
        return "❌ session_duration must be between 900 and 43 200 seconds."

    try:
        sts = boto3.client("sts")
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"BedrockSession-{uuid.uuid4().hex[:8]}",
            DurationSeconds=session_duration,
        )
        creds = response["Credentials"]
        expiration = creds["Expiration"].isoformat()
        logger.info("STS assume-role succeeded for %s.", role_arn)
        return (
            f"✅ Generated Bedrock credentials for '{role_arn}'.\n"
            f"   AWS_ACCESS_KEY_ID     = {creds['AccessKeyId']}\n"
            f"   AWS_SECRET_ACCESS_KEY = ****{creds['SecretAccessKey'][-4:]}\n"
            f"   AWS_SESSION_TOKEN     = ****{creds['SessionToken'][-8:]}\n"
            f"   Expiration            = {expiration}\n"
            f"   Duration              = {session_duration}s"
        )

    except NoCredentialsError:
        logger.warning("No AWS credentials – returning simulated response.")
        mock_access = f"ASIA{uuid.uuid4().hex[:16].upper()}"
        mock_secret = uuid.uuid4().hex
        mock_token = uuid.uuid4().hex + uuid.uuid4().hex
        return (
            f"[SIMULATED] ✅ Generated Bedrock credentials for '{role_arn}'.\n"
            f"   AWS_ACCESS_KEY_ID     = {mock_access}\n"
            f"   AWS_SECRET_ACCESS_KEY = {mock_secret}\n"
            f"   AWS_SESSION_TOKEN     = {mock_token}\n"
            f"   Expiration            = (now + {session_duration}s)\n"
            f"   Duration              = {session_duration}s"
        )

    except ClientError as exc:
        logger.error("STS ClientError: %s", exc)
        return f"❌ Failed to assume role: {exc}"

    except Exception as exc:
        logger.exception("Unexpected error in generate_bedrock_credentials")
        return f"❌ Unexpected error: {exc}"


# ===================================================================
# Tool 3 — Manage Secrets (local JSON store)
# ===================================================================

@mcp.tool()
def manage_secrets(action: str, key: str, value: str = "") -> str:
    """
    Manages a local JSON-based secret store at ``./devops_secrets.json``.

    Supported actions:
        * **get** — Retrieve a secret by key.
        * **set** — Create or update a secret (requires ``value``).
        * **list** — List all stored secret keys (values are masked).
        * **delete** — Remove a secret by key.

    Args:
        action: One of ``get``, ``set``, ``list``, ``delete``.
        key: The secret key to operate on (ignored for ``list``).
        value: The secret value (only required for ``set``).

    Returns:
        Result of the requested operation.
    """
    action = action.strip().lower()
    logger.info("manage_secrets called: action=%s key=%s", action, key)

    valid_actions = {"get", "set", "list", "delete"}
    if action not in valid_actions:
        return f"❌ Invalid action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}"

    try:
        secrets = _load_secrets()

        # --- GET -----------------------------------------------------------
        if action == "get":
            if key not in secrets:
                return f"❌ Secret '{key}' not found."
            return f"🔑 {key} = {secrets[key]}"

        # --- SET -----------------------------------------------------------
        if action == "set":
            if not value:
                return "❌ A non-empty 'value' is required for the 'set' action."
            is_update = key in secrets
            secrets[key] = value
            _save_secrets(secrets)
            verb = "Updated" if is_update else "Created"
            logger.info("%s secret '%s'.", verb, key)
            return f"✅ {verb} secret '{key}'."

        # --- LIST ----------------------------------------------------------
        if action == "list":
            if not secrets:
                return "📋 Secret store is empty."
            lines = ["📋 Stored secrets:"]
            for k in sorted(secrets):
                masked = secrets[k][:2] + "****" if len(secrets[k]) > 2 else "****"
                lines.append(f"   • {k} = {masked}")
            return "\n".join(lines)

        # --- DELETE --------------------------------------------------------
        if action == "delete":
            if key not in secrets:
                return f"❌ Secret '{key}' not found – nothing to delete."
            del secrets[key]
            _save_secrets(secrets)
            logger.info("Deleted secret '%s'.", key)
            return f"🗑️ Deleted secret '{key}'."

    except Exception as exc:
        logger.exception("Unexpected error in manage_secrets")
        return f"❌ Unexpected error: {exc}"

    # Should never reach here
    return "❌ Unknown error."


# ===================================================================
# Tool 4 — Create IAM Policy Document
# ===================================================================

@mcp.tool()
def create_iam_policy(
    service_name: str,
    actions: str,
    resource_arn: str = "*",
) -> str:
    """
    Generates a valid AWS IAM policy JSON document.

    This is a pure-logic tool — no AWS API call is made.

    Args:
        service_name: AWS service prefix, e.g. ``s3``, ``bedrock``,
                      ``dynamodb``.
        actions: Comma-separated action suffixes, e.g.
                 ``"GetObject,PutObject"`` -> ``s3:GetObject, s3:PutObject``.
        resource_arn: The resource ARN the policy applies to (default ``*``).

    Returns:
        A formatted IAM policy JSON document ready for ``aws iam
        create-policy``.
    """
    logger.info(
        "create_iam_policy called: service=%s actions=%s resource=%s",
        service_name, actions, resource_arn,
    )

    if not service_name:
        return "❌ 'service_name' is required (e.g. s3, bedrock, dynamodb)."
    if not actions:
        return "❌ 'actions' is required (comma-separated action suffixes)."

    qualified_actions = [
        f"{service_name.strip()}:{a.strip()}"
        for a in actions.split(",")
        if a.strip()
    ]

    if not qualified_actions:
        return "❌ No valid actions parsed. Provide comma-separated suffixes like 'GetObject,PutObject'."

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": f"Allow{service_name.capitalize()}Access",
                "Effect": "Allow",
                "Action": qualified_actions,
                "Resource": resource_arn,
            }
        ],
    }

    policy_json = json.dumps(policy, indent=2)
    logger.info("Generated IAM policy with %d action(s).", len(qualified_actions))
    return (
        f"✅ Generated IAM policy for service '{service_name}':\n\n"
        f"{policy_json}"
    )


# ===================================================================
# Tool 5 — Deploy Docker Container (SIMULATED)
# ===================================================================

@mcp.tool()
def deploy_docker_container(
    image_name: str,
    tag: str = "latest",
    port: int = 8080,
) -> str:
    """
    [SIMULATED] Runs a docker build -> push -> deploy workflow and returns
    the resulting deployment URL and container ID.

    Args:
        image_name: Docker image name (e.g. ``myapp`` or ``org/myapp``).
        tag: Image tag (default ``latest``).
        port: Host port to expose (default 8080).

    Returns:
        Simulated deployment summary including URL and container ID.
    """
    logger.info(
        "deploy_docker_container called: image=%s tag=%s port=%d",
        image_name, tag, port,
    )

    if not image_name:
        return "❌ 'image_name' is required."
    if not 1 <= port <= 65535:
        return "❌ 'port' must be between 1 and 65 535."

    container_id = uuid.uuid4().hex[:12]
    image_digest = f"sha256:{uuid.uuid4().hex}"
    deploy_url = f"https://{image_name.replace('/', '-')}-{container_id[:6]}.deploy.internal:{port}"
    registry_uri = f"registry.internal/{image_name}:{tag}"

    return (
        f"[SIMULATED] ✅ Docker deployment complete.\n"
        f"   Image        : {image_name}:{tag}\n"
        f"   Registry     : {registry_uri}\n"
        f"   Digest       : {image_digest}\n"
        f"   Container ID : {container_id}\n"
        f"   Port          : {port}\n"
        f"   Endpoint     : {deploy_url}\n"
        f"\n"
        f"   Pipeline stages executed:\n"
        f"     1. docker build -t {image_name}:{tag} .\n"
        f"     2. docker tag {image_name}:{tag} {registry_uri}\n"
        f"     3. docker push {registry_uri}\n"
        f"     4. kubectl set image deployment/{image_name} {image_name}={registry_uri}\n"
        f"   Status       : Running ✔"
    )


# ===================================================================
# Tool 6 — Check Service Health (REAL)
# ===================================================================

@mcp.tool()
def check_service_health(endpoint_url: str) -> str:
    """
    Makes a real HTTP GET request to the given URL and returns the
    status code, response time, and a snippet of the response body.

    Args:
        endpoint_url: Fully-qualified URL to probe
                      (e.g. ``https://api.example.com/health``).

    Returns:
        Health-check report with status code, latency, and body preview.
    """
    logger.info("check_service_health called: url=%s", endpoint_url)

    if not endpoint_url:
        return "❌ 'endpoint_url' is required."
    if not endpoint_url.startswith(("http://", "https://")):
        return "❌ 'endpoint_url' must start with http:// or https://."

    try:
        start = time.time()
        resp = requests.get(endpoint_url, timeout=5, allow_redirects=True)
        elapsed_ms = (time.time() - start) * 1000

        body_snippet = resp.text[:500]
        if len(resp.text) > 500:
            body_snippet += "\n… (truncated)"

        status_emoji = "✅" if resp.ok else "⚠️"

        return (
            f"{status_emoji} Health check for {endpoint_url}\n"
            f"   Status Code  : {resp.status_code} {resp.reason}\n"
            f"   Response Time: {elapsed_ms:.1f} ms\n"
            f"   Content-Type : {resp.headers.get('Content-Type', 'N/A')}\n"
            f"   Body Preview :\n{body_snippet}"
        )

    except requests.ConnectionError:
        logger.error("Connection error reaching %s", endpoint_url)
        return f"❌ Connection error: could not reach {endpoint_url}."

    except requests.Timeout:
        logger.error("Timeout reaching %s", endpoint_url)
        return f"❌ Timeout: {endpoint_url} did not respond within 5 s."

    except requests.RequestException as exc:
        logger.error("Request error: %s", exc)
        return f"❌ Request failed: {exc}"

    except Exception as exc:
        logger.exception("Unexpected error in check_service_health")
        return f"❌ Unexpected error: {exc}"


# ===================================================================
# Entrypoint
# ===================================================================

if __name__ == "__main__":
    mcp.run()
