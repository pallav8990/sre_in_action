# utils/proxy.py
from typing import Dict, Mapping, Callable, Awaitable
import asyncio, logging, httpx, os
from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from starlette.datastructures import Headers
from urllib.parse import urljoin
from models.proxy import UpstreamInfo
from common.connectors import registry

HOP_BY_HOP = {
    "connection","proxy-connection","keep-alive","proxy-authenticate",
    "proxy-authorization","te","trailer","transfer-encoding","upgrade"
}

client = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=float(os.getenv("PROXY_CONNECT_TIMEOUT", 5)),
        read=float(os.getenv("PROXY_READ_TIMEOUT", 60)),
        write=float(os.getenv("PROXY_WRITE_TIMEOUT", 60)),
    ),
    limits=httpx.Limits(
        max_keepalive_connections=int(os.getenv("PROXY_MAX_KEEPALIVE", 100)),
        max_connections=int(os.getenv("PROXY_MAX_CONNECTIONS", 200)),
    ),
    verify=(os.getenv("PROXY_CA_BUNDLE") or (os.getenv("PROXY_VERIFY_SSL","true").lower() != "false")),
    follow_redirects=False,
)

log = logging.getLogger("srehub.proxier")

def _filtered_request_headers(incoming: Headers) -> Dict[str, str]:
    out: Dict[str, str] = {}
    connection_tokens = set()
    if "connection" in incoming:
        connection_tokens.update([h.strip().lower() for h in incoming.get("connection","").split(",")])
    for k, v in incoming.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in connection_tokens:
            continue
        if lk in ("host","authorization"):  # do not forward caller Authorization
            continue
        out[k] = v
    return out

def _filtered_response_headers(incoming: Mapping[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    connection_tokens = set()
    if incoming.get("connection"):
        connection_tokens.update([h.strip().lower() for h in incoming["connection"].split(",")])
    for k, v in incoming.items():
        if k.lower() in HOP_BY_HOP or k.lower() in connection_tokens:
            continue
        out[k] = v
    return out

async def _backoff_retry(coro_factory: Callable[[], Awaitable[httpx.Response]], retries: int = int(os.getenv("PROXY_RETRIES", 1))):
    last = None
    for attempt in range(retries + 1):
        try:
            return await coro_factory()
        except (httpx.TransportError, httpx.ReadTimeout) as e:
            last = e
            if attempt >= retries:
                break
            await asyncio.sleep(0.5 * (2 ** attempt))
    raise last  # type: ignore

async def proxy_request(request: Request, connector: str, path: str) -> Response:
    up: UpstreamInfo = registry.resolve(connector)
    target = urljoin(up.base_url, path)
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = _filtered_request_headers(request.headers)

    # X-Forwarded-*
    client_host = request.client.host if request.client else ""
    prior_xff = request.headers.get("x-forwarded-for")
    xff = f"{prior_xff}, {client_host}" if prior_xff else client_host
    headers["X-Forwarded-For"] = xff
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "")

    # traceparent passthrough if present
    if "traceparent" in request.headers:
        headers["traceparent"] = request.headers["traceparent"]

    # Inject connector credentials
    headers.update(up.auth_headers)

    body = await request.body()

    async def _go():
        return await client.request(request.method, target, headers=headers, content=(body if body else None))

    try:
        resp = await _backoff_retry(_go)
    except httpx.HTTPError as e:
        log.warning("Upstream error %s %s -> %s: %s", request.method, request.url.path, target, e)
        raise HTTPException(status_code=502, detail="Bad gateway (upstream error)")

    out_headers = _filtered_response_headers(resp.headers)
    media_type = out_headers.get("content-type")

    async def _iter():
        async for chunk in resp.aiter_bytes():
            yield chunk

    return StreamingResponse(_iter(), status_code=resp.status_code, media_type=media_type, headers=out_headers)