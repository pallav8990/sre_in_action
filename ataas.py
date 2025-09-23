# api/v1/ataas.py
from fastapi import APIRouter, Request
from utils.proxy import proxy_request  # moved to utils

router = APIRouter(prefix="/api/v1/ataas", tags=["ATAAS"])

@router.get("/health")
async def ataas_health():
    return {"ok": True}

# Any non-implemented path/method is proxied to ATAAS:
@router.api_route("/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"])
async def ataas_fallback(path: str, request: Request):
    return await proxy_request(request, connector="ataas", path=path)