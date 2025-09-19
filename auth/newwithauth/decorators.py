# auth/decorators.py
from functools import wraps
from typing import Callable, Iterable, Optional, Dict, Any, Union
import os, time, asyncio, jwt, httpx
from jwt import PyJWKClient
from fastapi import Request, HTTPException
from fastapi.routing import APIRouter
from .sso import PingOIDC


class RequireAuth:
    """
    OIDC authentication + optional external authorization.
    Can wrap a single route function or an APIRouter (router-level).
    """

    def __init__(
        self,
        oidc: PingOIDC,
        # Optional OIDC-based checks
        require_scopes: Optional[Iterable[str]] = None,
        any_scope_ok: bool = True,
        require_roles_claim: Optional[str] = None,
        require_roles: Optional[Iterable[str]] = None,
        clock_skew: int = 60,

        # External authorization API
        authz_api_url: Optional[str] = None,
        authz_action: Optional[str] = None,
        authz_timeout_secs: float = 3.0,
        authz_headers_provider: Optional[Callable[[], "dict|Awaitable[dict]"]] = None,

        # Cache
        decision_ttl_secs: int = 30,
        decision_cache_size: int = 1024,
        deny_on_error: bool = True,
    ):
        self.oidc = oidc
        self.require_scopes = set(require_scopes or [])
        self.any_scope_ok = any_scope_ok
        self.roles_claim = require_roles_claim
        self.require_roles = set(require_roles or [])
        self.clock_skew = clock_skew

        self.authz_api_url = authz_api_url or os.getenv("AUTHZ_API_URL")
        self.authz_action = authz_action
        self.authz_timeout_secs = authz_timeout_secs
        self.authz_headers_provider = authz_headers_provider

        self.decision_ttl_secs = decision_ttl_secs
        self.decision_cache_size = decision_cache_size
        self.deny_on_error = deny_on_error

        self._decisions: Dict[str, tuple] = {}
        self._decisions_order: list[str] = []
        self._decisions_lock = asyncio.Lock()

        self._jwks_client = None
        self._jwks_issuer = None

    # --------- Helpers ----------
    async def _jwks(self):
        cfg = await self.oidc.discover()
        if not self._jwks_client or self._jwks_issuer != cfg["issuer"]:
            self._jwks_client = PyJWKClient(cfg["jwks_uri"])
            self._jwks_issuer = cfg["issuer"]
        return cfg, self._jwks_client

    async def _ensure_token(self, request: Request) -> Dict[str, Any]:
        tok = request.session.get("token")
        if not tok:
            request.session["next"] = request.url.path + (
                f"?{request.url.query}" if request.url.query else ""
            )
            raise HTTPException(401, "Not authenticated")

        if tok.get("refresh_token") and int(time.time()) > int(tok.get("expires_at", 0)) - 120:
            try:
                new_tok = await self.oidc.refresh(tok["refresh_token"])
                tok.update({
                    "access_token": new_tok["access_token"],
                    "refresh_token": new_tok.get("refresh_token", tok["refresh_token"]),
                    "expires_at": int(time.time()) + int(new_tok.get("expires_in", 3600)),
                    "id_token": new_tok.get("id_token", tok.get("id_token")),
                    "token_type": new_tok.get("token_type", "Bearer"),
                })
                request.session["token"] = tok
            except Exception:
                raise HTTPException(401, "Session expired. Please log in again.")
        return tok

    def _extract_claim(self, obj: Dict[str, Any], dotted: str):
        cur = obj
        for p in dotted.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return None
        return cur

    def _cache_key(self, subject: str, action: Optional[str]) -> str:
        return f"{subject}|{action or ''}"

    async def _authz_headers(self) -> Dict[str, str]:
        if not self.authz_headers_provider:
            return {}
        h = self.authz_headers_provider()
        if asyncio.iscoroutine(h):
            h = await h
        return h or {}

    async def _check_authorization(self, subject: str, email: Optional[str], action: Optional[str]) -> bool:
        """Call external authorization API. Expects { "allowed": true/false }."""
        if not self.authz_api_url:
            return True

        key = self._cache_key(subject, action)
        now = time.time()
        async with self._decisions_lock:
            entry = self._decisions.get(key)
            if entry and entry[1] > now:
                return entry[0]

        payload = {"subject": subject, "email": email, "action": action}
        try:
            headers = {"Content-Type": "application/json"}
            headers.update(await self._authz_headers())
            async with httpx.AsyncClient(timeout=self.authz_timeout_secs) as c:
                r = await c.post(self.authz_api_url, json=payload, headers=headers)
            if r.status_code != 200:
                return not self.deny_on_error
            allowed = bool(r.json().get("allowed"))
        except Exception:
            allowed = not self.deny_on_error

        exp = now + max(1, self.decision_ttl_secs)
        async with self._decisions_lock:
            self._decisions[key] = (allowed, exp)
            self._decisions_order.append(key)
            if len(self._decisions_order) > self.decision_cache_size:
                old = self._decisions_order.pop(0)
                self._decisions.pop(old, None)

        return allowed

    # --------- Wrapping ----------
    def _wrap_function(self, fn: Callable):
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            # locate Request
            request: Optional[Request] = kwargs.get("request")
            if request is None:
                for a in args:
                    if isinstance(a, Request):
                        request = a; break
            if request is None:
                raise HTTPException(500, "Request not found")

            # 1. Authenticate
            tok = await self._ensure_token(request)

            # 2. Verify ID token
            idt = tok.get("id_token")
            if not idt:
                raise HTTPException(401, "No ID token in session")

            cfg, jwks_client = await self._jwks()
            try:
                key = jwks_client.get_signing_key_from_jwt(idt)
                claims = jwt.decode(
                    idt, key.key,
                    algorithms=["RS256","RS384","RS512","ES256","ES384","ES512"],
                    audience=self.oidc.client_id,
                    issuer=cfg["issuer"],
                    leeway=self.clock_skew,
                )
            except Exception:
                raise HTTPException(401, "Invalid ID token")

            # 3. (Optional) OIDC scope/role checks
            if self.require_scopes:
                scp_raw = claims.get("scope") or claims.get("scp") or ""
                scopes = set(scp_raw.split()) if isinstance(scp_raw, str) else set(scp_raw or [])
                if self.any_scope_ok:
                    if self.require_scopes.isdisjoint(scopes):
                        raise HTTPException(403, "Insufficient scope")
                else:
                    if not self.require_scopes.issubset(scopes):
                        raise HTTPException(403, "Insufficient scope")

            if self.roles_claim and self.require_roles:
                roles = set(self._extract_claim(claims, self.roles_claim) or [])
                if not self.require_roles.issubset(roles):
                    raise HTTPException(403, "Insufficient role")

            # 4. External authz check
            subject = claims.get("sub")
            email = claims.get("email")
            allowed = await self._check_authorization(subject, email, self.authz_action)
            if not allowed:
                raise HTTPException(403, "Not authorized")

            # 5. Expose identity in request.state
            request.state.user = {
                "sub": subject,
                "email": email,
                "name": claims.get("name"),
                "claims": claims,
                "access_token": tok.get("access_token"),
            }

            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        return async_wrapper

    def __call__(self, target: Union[Callable, APIRouter]):
        from fastapi.routing import APIRouter as _R
        if callable(target) and not isinstance(target, _R):
            return self._wrap_function(target)
        if isinstance(target, _R):
            for route in target.routes:
                if hasattr(route, "endpoint"):
                    route.endpoint = self._wrap_function(route.endpoint)
            return target
        raise TypeError("RequireAuth can wrap a route function or an APIRouter")