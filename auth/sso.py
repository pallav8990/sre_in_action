import os
import httpx
from typing import Optional, Dict, Any
from authlib.integrations.httpx_client import AsyncOAuth2Client

class PingOIDC:
    """
    Minimal OIDC helper for Ping (PingFederate/PingOne) using confidential client.
    No PKCE. Authorization Code + Refresh Token.
    """
    def __init__(self, prefix: str = "PING_"):
        self.issuer = os.environ[f"{prefix}ISSUER"].rstrip("/")
        self.client_id = os.environ[f"{prefix}CLIENT_ID"]
        self.client_secret = os.environ[f"{prefix}CLIENT_SECRET"]
        self.redirect_uri = os.environ[f"{prefix}REDIRECT_URI"]
        self.scopes = os.environ.get(f"{prefix}SCOPES", "openid profile email offline_access").split()
        # client_secret_basic (default) or client_secret_post
        self.token_auth_method = os.environ.get(f"{prefix}TOKEN_AUTH_METHOD", "client_secret_basic")
        self._cfg: Optional[Dict[str, Any]] = None

    async def discover(self) -> Dict[str, Any]:
        if self._cfg:
            return self._cfg
        url = f"{self.issuer}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url)
            r.raise_for_status()
            self._cfg = r.json()
        return self._cfg

    async def client(self, token: Optional[Dict[str, Any]] = None) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            client_id=self.client_id,
            client_secret=self.client_secret,
            token=token,
            token_endpoint_auth_method=self.token_auth_method,
            scope=" ".join(self.scopes),
            redirect_uri=self.redirect_uri,
            timeout=15,
        )

    async def auth_url(self, state: str):
        cfg = await self.discover()
        async with await self.client() as oauth:
            # Returns (authorization_url, state)
            return oauth.create_authorization_url(
                cfg["authorization_endpoint"],
                response_type="code",
                state=state,
                # Uncomment once if Ping needs this to mint refresh_token:
                # prompt="consent",
            )

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        cfg = await self.discover()
        async with await self.client() as oauth:
            return await oauth.fetch_token(
                cfg["token_endpoint"],
                code=code,
                grant_type="authorization_code",
            )

    async def refresh(self, refresh_token: str) -> Dict[str, Any]:
        cfg = await self.discover()
        async with await self.client() as oauth:
            return await oauth.refresh_token(
                cfg["token_endpoint"],
                refresh_token=refresh_token,
                grant_type="refresh_token",
            )