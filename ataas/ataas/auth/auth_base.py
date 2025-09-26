from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict
import os, base64, time, httpx

# ---- Strategy contract ----
class AuthStrategy(ABC):
    @abstractmethod
    async def headers(self) -> Dict[str, str]:
        ...

# ---- Concrete strategies (shared by all connectors) ----
class ApiKeyAuth(AuthStrategy):
    def __init__(self, key: str, key_header: str = "x-api-key"):
        self._key, self._key_header = key, key_header
    async def headers(self) -> Dict[str, str]:
        return {self._key_header: self._key}

class BearerTokenAuth(AuthStrategy):
    def __init__(self, token: str, header: str = "Authorization"):
        self._token, self._header = token, header
    async def headers(self) -> Dict[str, str]:
        return {self._header: f"Bearer {self._token}"}

class BasicAuth(AuthStrategy):
    def __init__(self, username: str, password: str, header: str = "Authorization"):
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._headers = {header: f"Basic {token}"}
    async def headers(self) -> Dict[str, str]:
        return dict(self._headers)

class OAuth2ClientCredentials(AuthStrategy):
    def __init__(self, token_url: str, client_id: str, client_secret: str,
                 scope: str | None = None, auth_method: str = "client_secret_basic",
                 audience: str | None = None, timeout_sec: float = 10.0):
        self.token_url, self.client_id, self.client_secret = token_url, client_id, client_secret
        self.scope, self.auth_method, self.audience = scope, auth_method, audience
        self.timeout_sec = timeout_sec
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def headers(self) -> Dict[str, str]:
        now = time.time()
        if not self._access_token or now + 30 >= self._expires_at:
            await self._refresh()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _refresh(self) -> None:
        data = {"grant_type": "client_credentials"}
        if self.scope: data["scope"] = self.scope
        if self.audience: data["audience"] = self.audience
        auth = (self.client_id, self.client_secret) if self.auth_method == "client_secret_basic" else None
        if auth is None:
            data["client_id"] = self.client_id
            data["client_secret"] = self.client_secret
        async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
            r = await client.post(self.token_url, data=data,
                                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                                  auth=auth)
            r.raise_for_status()
            body = r.json()
        self._access_token = body["access_token"]
        self._expires_at = time.time() + max(60, int(0.9 * int(body.get("expires_in", 3600))))

# ---- Env factory (per-connector prefix) ----
def auth_from_env(prefix: str) -> AuthStrategy:
    t = os.getenv(f"{prefix}_AUTH_TYPE", "api_key").lower()
    if t == "api_key":
        return ApiKeyAuth(
            key=os.getenv(f"{prefix}_API_KEY", ""),
            key_header=os.getenv(f"{prefix}_API_KEY_HEADER", "x-api-key"),
        )
    if t == "bearer":
        return BearerTokenAuth(token=os.getenv(f"{prefix}_BEARER_TOKEN", ""))
    if t == "basic":
        return BasicAuth(
            username=os.getenv(f"{prefix}_BASIC_USER", ""),
            password=os.getenv(f"{prefix}_BASIC_PASS", ""),
        )
    if t == "oauth2_cc":
        return OAuth2ClientCredentials(
            token_url=os.getenv(f"{prefix}_OAUTH_TOKEN_URL", ""),
            client_id=os.getenv(f"{prefix}_OAUTH_CLIENT_ID", ""),
            client_secret=os.getenv(f"{prefix}_OAUTH_CLIENT_SECRET", ""),
            scope=os.getenv(f"{prefix}_OAUTH_SCOPE") or None,
            auth_method=os.getenv(f"{prefix}_OAUTH_CLIENT_AUTH_METHOD", "client_secret_basic"),
            audience=os.getenv(f"{prefix}_OAUTH_AUDIENCE") or None,
        )
    return ApiKeyAuth(key=os.getenv(f"{prefix}_API_KEY", ""), key_header=os.getenv(f"{prefix}_API_KEY_HEADER", "x-api-key"))