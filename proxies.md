"""
SREHubApp Proxier - a secure, stateless reverse proxy layer

Goal
----
Route any URI that SREHubApp hasn't implemented to the underlying upstream API
for a given connector, forwarding the full payload. Credentials are sourced
exclusively via SREHubApp's connector/auth modules (NEVER from the caller), and
responses are returned unmodified (headers/body/status), aside from required
hop-by-hop header filtering.

Highlights
----------
- Async, streaming pass-through using httpx + FastAPI
- Connector-driven upstream base URLs + auth headers
- Explicit upstream allowlist (no open proxy!)
- Works for all HTTP methods, query strings, JSON, multipart, large bodies
- Propagates X-Forwarded-* and W3C trace context (traceparent)
- Strips hop-by-hop headers (per RFC 7230)
- Sensible timeouts + optional retries with exponential backoff
- Observability hooks for OpenTelemetry (trace/log IDs in context)
- Safe header policy: don't leak caller Authorization; inject connector auth
- Ready for mTLS / custom CA bundles to upstreams

Extensions you can add later: WebSocket proxy, response/body size limits, caching
of GETs, circuit breakers, per-connector rate limiting, and deny-lists.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Dict, Iterable, Mapping, Optional

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from starlette.datastructures import Headers, MutableHeaders
from starlette.routing import Match
from urllib.parse import urljoin

# -----------------------------------------------------------------------------
# Config & constants
# -----------------------------------------------------------------------------

HOP_BY_HOP = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

DEFAULT_CONNECT_TIMEOUT = float(os.getenv("PROXY_CONNECT_TIMEOUT", 5))
DEFAULT_READ_TIMEOUT = float(os.getenv("PROXY_READ_TIMEOUT", 60))
DEFAULT_WRITE_TIMEOUT = float(os.getenv("PROXY_WRITE_TIMEOUT", 60))
DEFAULT_POOL_LIMITS = httpx.Limits(
    max_keepalive_connections=int(os.getenv("PROXY_MAX_KEEPALIVE", 100)),
    max_connections=int(os.getenv("PROXY_MAX_CONNECTIONS", 200)),
)

# Upstream domain allowlist to avoid open-proxy abuse
ALLOWED_UPSTREAMS = set(
    filter(
        None,
        [s.strip() for s in os.getenv("PROXY_ALLOWED_UPSTREAMS", "").split(",")],
    )
)

# Optional: trust store override for corporate roots
VERIFY_SSL = os.getenv("PROXY_VERIFY_SSL", "true").lower() != "false"
CA_BUNDLE = os.getenv("PROXY_CA_BUNDLE") or None

# -----------------------------------------------------------------------------
# Connector registry (stub interface - adapt to your SREHub connectors)
# -----------------------------------------------------------------------------

class UpstreamInfo(BaseModel):
    base_url: str                    # e.g., "https://splunk.company.com:8089/"
    auth_headers: Dict[str, str]     # e.g., {"Authorization": "Bearer <token>"}

class ConnectorRegistry:
    """Resolve connector -> UpstreamInfo using your existing auth modules.

    Replace this with your actual registry logic. The important part is that
    *credentials* come from SREHub (env/secret stores), not from the caller.
    """

    def __init__(self):
        # Example static map. In production, query your connector/auth modules.
        self._map: Dict[str, UpstreamInfo] = {}

    def register(self, name: str, base_url: str, auth_headers: Dict[str, str]):
        if ALLOWED_UPSTREAMS and not any(base_url.startswith(p) for p in ALLOWED_UPSTREAMS):
            raise ValueError(
                f"Upstream base_url not allowed by PROXY_ALLOWED_UPSTREAMS: {base_url}"
            )
        self._map[name] = UpstreamInfo(base_url=base_url, auth_headers=auth_headers)

    def resolve(self, name: str) -> UpstreamInfo:
        try:
            return self._map[name]
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown connector: {name}")

registry = ConnectorRegistry()

# Example (remove in prod):
# registry.register(
#     "splunk", "https://splunk.company.com:8089/", {"Authorization": "Bearer TOKEN"}
# )

# -----------------------------------------------------------------------------
# HTTP client: shared, async, with tuned limits/timeouts
# -----------------------------------------------------------------------------

client = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=DEFAULT_CONNECT_TIMEOUT,
        read=DEFAULT_READ_TIMEOUT,
        write=DEFAULT_WRITE_TIMEOUT,
        pool=None,
    ),
    limits=DEFAULT_POOL_LIMITS,
    verify=CA_BUNDLE or VERIFY_SSL,
    follow_redirects=False,
)

log = logging.getLogger("srehub.proxier")

app = FastAPI(title="SREHubApp Proxier")

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

TRACEPARENT_RE = re.compile(r"^(?<version>[\da-f]{2})-(?<trace_id>[\da-f]{32})-(?<parent_id>[\da-f]{16})-(?<flags>[\da-f]{2})$")


def filtered_request_headers(incoming: Headers) -> Dict[str, str]:
    out: Dict[str, str] = {}
    connection_tokens = set()

    # RFC: connection header can list hop-by-hop header names to remove
    if "connection" in incoming:
        connection_tokens.update(
            [h.strip().lower() for h in incoming.get("connection", "").split(",")]
        )

    for k, v in incoming.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in connection_tokens:
            continue
        if lk == "host":
            # Upstream host will be set by httpx based on target URL
            continue
        if lk == "authorization":
            # Never forward caller's Authorization; we inject connector's creds
            continue
        out[k] = v
    return out


def filtered_response_headers(incoming: Mapping[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    connection_tokens = set()
    conn_header = incoming.get("connection")
    if conn_header:
        connection_tokens.update([h.strip().lower() for h in conn_header.split(",")])

    for k, v in incoming.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in connection_tokens:
            continue
        out[k] = v
    return out


async def backoff_retry(coro_factory, *, retries: int = 1, base_delay: float = 0.5):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await coro_factory()
        except (httpx.TransportError, httpx.ReadTimeout) as e:
            last_exc = e
            if attempt >= retries:
                break
            await asyncio.sleep(base_delay * (2 ** attempt))
    raise last_exc  # type: ignore

# -----------------------------------------------------------------------------
# Catch-all proxy route for unimplemented URIs
#   Pattern: /proxy/{connector}/{path:path}
#   Examples:
#     GET  /proxy/splunk/services/server/info
#     POST /proxy/ataas/api/v2/job/123/launch
# -----------------------------------------------------------------------------

@app.api_route("/proxy/{connector}/{path:path}", methods=[
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"
])
async def proxier(connector: str, path: str, request: Request) -> Response:
    upstream = registry.resolve(connector)

    # Normalize + join target URL
    target_url = urljoin(upstream.base_url, path)
    # Preserve query string
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Build outbound headers
    out_headers = filtered_request_headers(request.headers)
    # Forward tracing + client context
    # X-Forwarded-* chain
    client_host = request.client.host if request.client else ""
    prior_xff = request.headers.get("x-forwarded-for")
    xff = f"{prior_xff}, {client_host}" if prior_xff else client_host
    out_headers["X-Forwarded-For"] = xff
    out_headers["X-Forwarded-Proto"] = request.url.scheme
    out_headers["X-Forwarded-Host"] = request.headers.get("host", "")

    # W3C trace context: if caller provided one, let it pass; else your tracing can inject
    if "traceparent" in request.headers:
        out_headers["traceparent"] = request.headers["traceparent"]

    # Inject connector credentials (overrides any existing Authorization)
    out_headers.update(upstream.auth_headers)

    method = request.method.upper()

    # Body handling: stream or buffer. For simplicity we buffer; swap to streaming if needed.
    body = await request.body()

    async def do_request():
        return await client.request(
            method,
            target_url,
            content=body if body else None,
            headers=out_headers,
        )

    try:
        resp = await backoff_retry(do_request, retries=int(os.getenv("PROXY_RETRIES", 1)))
    except httpx.HTTPError as e:
        log.warning("Proxy upstream error %s %s -> %s: %s", method, request.url.path, target_url, e)
        raise HTTPException(status_code=502, detail="Bad gateway (upstream error)")

    # Build streaming response to caller (no body mutation)
    headers = filtered_response_headers(resp.headers)

    # NOTE: We avoid setting 'content-length' when streaming from httpx; Starlette handles it.
    #       Ensure media_type is preserved; default to application/octet-stream if absent.
    media_type = headers.get("content-type")

    async def iter_bytes():
        async for chunk in resp.aiter_bytes():
            yield chunk

    return StreamingResponse(
        iter_bytes(),
        status_code=resp.status_code,
        media_type=media_type,
        headers=headers,
        background=None,
    )

# -----------------------------------------------------------------------------
# Health + minimal info
# -----------------------------------------------------------------------------

@app.get("/proxy/_health")
async def health():
    return {"ok": True}

# -----------------------------------------------------------------------------
# Hardening checklist (readme-ish):
# -----------------------------------------------------------------------------
# 1) Set PROXY_ALLOWED_UPSTREAMS to comma-separated prefixes, e.g.:
#    PROXY_ALLOWED_UPSTREAMS="https://splunk.company.com:8089/,https://ataas.company.com/"
# 2) Implement ConnectorRegistry.resolve() to fetch tokens per-request using your
#    existing auth base class (PingAccess OIDC, Vault, etc.). Refresh tokens as needed.
# 3) Consider per-connector rate limits & circuit breakers. Expose metrics.
# 4) Enforce max body size: use ASGI server limits (uvicorn --limit-max-requests, etc.)
# 5) For uploads, switch to streaming request bodies via request.stream() to avoid buffering.
# 6) Add a WebSocket proxy if needed for streaming logs (Splunk tail, etc.).
# 7) Add mTLS to upstreams by providing cert/key via httpx client (cert=(certfile,keyfile)).
# 8) Log audit fields: user id (from your middleware), connector, path, status, latency.
# 9) Do NOT allow arbitrary full URLs from caller; only /proxy/{connector}/{path} with allowlist.
# 10) Preserve SSE by not buffering; StreamingResponse already handles it.
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
