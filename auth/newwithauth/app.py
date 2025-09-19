# app.py
import os, secrets
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from starlette.middleware.sessions import SessionMiddleware

from auth.sso import PingOIDC
from auth.decorators import RequireAuth
from auth import routes as auth_routes

app = FastAPI(docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(32)),
    https_only=True,
    same_site=os.getenv("SESSION_SAMESITE","lax"),
    session_cookie=os.getenv("SESSION_COOKIE","srehubapp_sid"),
)

# mount auth routes
app.include_router(auth_routes.router)

# protect docs with RequireAuth + external authz if you want
authz_for_docs = RequireAuth(
    PingOIDC(),
    authz_api_url=os.getenv("AUTHZ_API_URL"),   # optional external check
    authz_action="view_docs",
    deny_on_error=True,
)

# static swagger
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/docs")
@authz_for_docs
async def docs(_: Request):
    return FileResponse("static/swagger.html")

@app.get("/openapi.json")
@authz_for_docs
async def openapi_json(_: Request):
    return JSONResponse(get_openapi(title="SREHubApp", version="1.0.0", routes=app.routes))