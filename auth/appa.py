import os, time, secrets
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from auth.ping_oidc import PingOIDC
from auth.decorators import RequireAuth

app = FastAPI()

# Session cookie -> keep small; store tokens server-side (this demo puts tokens in session directly)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", secrets.token_hex(32)),
    https_only=True,
    same_site="lax"
)

oidc = PingOIDC()

@app.get("/auth/login")
async def login(request: Request):
    state = secrets.token_urlsafe(24)
    request.session["oidc_state"] = state
    auth_url, _state = await oidc.auth_url(state=state)
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    if not code or state != request.session.get("oidc_state"):
        raise HTTPException(400, "Invalid state or code")
    tok = await oidc.exchange_code(code)
    request.session["token"] = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "expires_at": int(time.time()) + int(tok.get("expires_in", 3600)),
        "id_token": tok.get("id_token"),
        "token_type": tok.get("token_type", "Bearer"),
    }
    return RedirectResponse("/me")

@app.get("/auth/logout")
async def logout(request: Request):
    # Local session clear; optionally redirect to Ping end_session_endpoint for global logout
    request.session.clear()
    return JSONResponse({"ok": True})

# ── Reusable decorators
roles_claim = os.getenv("PING_ROLES_CLAIM", "roles")  # adjust to your Ping mapping
require_auth = RequireAuth(oidc)  # basic login required
require_ops = RequireAuth(oidc, require_scopes={"ops.read"})  # example scope guard
require_admin = RequireAuth(oidc, require_roles_claim=roles_claim, require_roles={"admin"})  # example role guard

@app.get("/me")
@require_auth
async def me(request: Request):
    u = request.state.user
    return JSONResponse({"sub": u["sub"], "email": u.get("email"), "name": u.get("name")})

@app.get("/ops/data")
@require_ops
async def ops_data(request: Request):
    # Example of forwarding token to downstream API: request.state.user["access_token"]
    return {"ok": True, "has_access_token": bool(request.state.user["access_token"])}

@app.get("/admin/rotate")
@require_admin
async def admin_rotate(_: Request):
    return {"rotated": True}