from functools import wraps
from typing import Callable, Iterable, Optional, Dict, Any
import time, asyncio, jwt
from jwt import PyJWKClient
from fastapi import Request, HTTPException
from .ping_oidc import PingOIDC

class RequireAuth:
    """
    Class-based decorator for FastAPI routes.
    - Ensures session has tokens
    - Auto-refreshes access_token if near expiry
    - Validates id_token (issuer/audience/signature)
    - Optional scope/role checks
    - Injects request.state.user
    """
    def __init__(
        self,
        oidc: PingOIDC,
        require_scopes: Optional[Iterable[str]] = None,
        any_scope_ok: bool = True,
        require_roles_claim: Optional[str] = None,   # e.g., "roles" or "realm_access.roles"
        require_roles: Optional[Iterable[str]] = None,
        clock_skew: int = 60,
    ):
        self.oidc = oidc
        self.require_scopes = set(require_scopes or [])
        self.any_scope_ok = any_scope_ok
        self.roles_claim = require_roles_claim
        self.require_roles = set(require_roles or [])
        self.clock_skew = clock_skew
        self._jwks_client = None
        self._jwks_issuer = None

    async def _jwks(self):
        cfg = await self.oidc.discover()
        if not self._jwks_client or self._jwks_issuer != cfg["issuer"]:
            self._jwks_client = PyJWKClient(cfg["jwks_uri"])
            self._jwks_issuer = cfg["issuer"]
        return cfg, self._jwks_client

    async def _ensure_token(self, request: Request) -> Dict[str, Any]:
        tok = request.session.get("token")
        if not tok:
            raise HTTPException(401, "Not authenticated")

        # Refresh if expiring in < 120 seconds
        if tok.get("refresh_token") and int(time.time()) > int(tok.get("expires_at", 0)) - 120:
            try:
                new_tok = await self.oidc.refresh(tok["refresh_token"])
                tok.update({
                    "access_token": new_tok["access_token"],
                    "refresh_token": new_tok.get("refresh_token", tok.get("refresh_token")),  # rotation-aware
                    "expires_at": int(time.time()) + int(new_tok.get("expires_in", 3600)),
                    "id_token": new_tok.get("id_token", tok.get("id_token")),
                    "token_type": new_tok.get("token_type", tok.get("token_type", "Bearer")),
                })
                request.session["token"] = tok
            except Exception:
                raise HTTPException(401, "Session expired. Please log in again.")
        return tok

    def _extract_claim(self, obj: Dict[str, Any], dotted: str):
        # supports nested claim paths like "realm_access.roles"
        cur = obj
        for p in dotted.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return None
        return cur

    def __call__(self, fn: Callable):
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            # locate Request
            request: Optional[Request] = kwargs.get("request")
            if request is None:
                for a in args:
                    if isinstance(a, Request):
                        request = a; break
            if request is None:
                raise HTTPException(500, "Request object not found; add `request: Request` to your route")

            tok = await self._ensure_token(request)

            idt = tok.get("id_token")
            if not idt:
                raise HTTPException(401, "No ID token in session")

            cfg, jwks_client = await self._jwks()
            try:
                key = jwks_client.get_signing_key_from_jwt(idt)
                claims = jwt.decode(
                    idt,
                    key.key,
                    algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                    audience=self.oidc.client_id,
                    issuer=cfg["issuer"],
                    leeway=self.clock_skew,
                )
            except Exception:
                raise HTTPException(401, "Invalid ID token")

            # Scope checks
            if self.require_scopes:
                scp_raw = claims.get("scope") or claims.get("scp") or ""
                scopes = set(scp_raw.split()) if isinstance(scp_raw, str) else set(scp_raw or [])
                if self.any_scope_ok:
                    if self.require_scopes.isdisjoint(scopes):
                        raise HTTPException(403, "Insufficient scope")
                else:
                    if not self.require_scopes.issubset(scopes):
                        raise HTTPException(403, "Insufficient scope")

            # Role checks (optional)
            if self.roles_claim and self.require_roles:
                roles = set(self._extract_claim(claims, self.roles_claim) or [])
                if not self.require_roles.issubset(roles):
                    raise HTTPException(403, "Insufficient role")

            # Expose identity for downstream
            request.state.user = {
                "sub": claims.get("sub"),
                "email": claims.get("email"),
                "name": claims.get("name"),
                "claims": claims,
                "access_token": tok.get("access_token"),
                "token_type": tok.get("token_type", "Bearer"),
            }

            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)

        return async_wrapper