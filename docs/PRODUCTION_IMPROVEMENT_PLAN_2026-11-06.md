# Google Cloud Professional Agentic Architect: Production Improvement Plan
## Repository: ops-mcp-suite
**Audit Date:** November 6, 2026  
**Target Standard:** Google Cloud Professional Agentic Architect (Domain 2: Coding Agents & Domain 3: Custom Agents)

---

### Current Assessment
A modular micro-MCP platform comprising 6 specialized Model Context Protocol servers (DevOps, MLOps, AgentOps, DBOps, GitHub, Secrets) unified under a FastAPI gateway supporting both standard `stdio` and serverless SSE transports.

### Critical Gaps
1. **Unauthenticated SSE Endpoints:** The FastAPI SSE gateway currently accepts unauthenticated connections, violating zero-trust agentic security guidelines.
2. **Missing Token Auditing & Quotas:** Tool calls are executed without tracking token consumption or enforcing per-tenant rate limits.
3. **No Cloud Run Deployment Manifest:** Needs a unified container build and Terraform/Cloud Run deployment configuration.

---

### Actionable Implementation Steps

#### 1. Enforce Google Cloud ID Token Validation (OAuth 2.0)
Wrap the SSE gateway route with Google Cloud ID token verification:
```python
from fastapi import Request, HTTPException, Security
from google.oauth2 import id_token
from google.auth.transport import requests

async def verify_google_identity(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = auth_header.split(" ")[1]
    try:
        # Verify token against Google's public certs
        id_info = id_token.verify_oauth2_token(token, requests.Request())
        request.state.user = id_info
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Invalid Google ID token: {str(e)}")
```

#### 2. Implement Rate Limiting & Token Metering via Agent Gateway
Configure Google Cloud Agent Gateway routing policies to enforce a maximum of 100 tool invocations/minute per tenant.

#### 3. Standardize Multi-Stage Dockerfile
Create an optimized container packaging all 6 micro-servers under a single lightweight Python 3.12 image.

#### 4. Automated Tool Schema Fuzzing
Add unit tests that fuzz MCP input schemas with malformed parameters to prove tools fail gracefully with structured error payloads rather than throwing unhandled 500 exceptions.
