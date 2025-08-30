# Moved from top-level code.py to avoid shadowing Python's stdlib `code` module
# The original content appears to be example code for an auth layer and is kept here for reference.

# srehubapp/auth/base/auth_base.py

import os
import logging

try:
    from srehubapp.utils.logger import logger  # type: ignore
except Exception:
    # Fallback basic logger to keep this file importable in isolation
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("srehubapp_logger")


class AuthBase:
    def __init__(self, component_prefix: str):
        self.prefix = component_prefix.upper()
        self.client_id = os.getenv(f"{self.prefix}_CLIENT_ID")
        self.client_secret = os.getenv(f"{self.prefix}_CLIENT_SECRET")
        self.oauth_url = os.getenv(f"{self.prefix}_OAUTH_URL")

        logger.debug(f"[{self.prefix} AuthBase] Initialized with client_id and oauth_url")

        if not all([self.client_id, self.client_secret, self.oauth_url]):
            raise ValueError(f"[{self.prefix} AuthBase] Missing required environment variables.")

    async def get_access_token(self) -> str:
        raise NotImplementedError("get_access_token() must be implemented in child class.")


# srehubapp/auth/openshift_auth.py

try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None


class OpenShiftOAuthClient(AuthBase):
    def __init__(self, cluster: str):
        super().__init__(component_prefix="OCP")
        self.cluster = cluster

    async def get_access_token(self) -> str:
        logger.info(f"[OCP] Requesting token for cluster {self.cluster}")
        if aiohttp is None:
            raise RuntimeError("aiohttp not installed")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }

        async with aiohttp.ClientSession() as session:  # type: ignore
            async with session.post(self.oauth_url, data=data) as resp:  # type: ignore
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"[OCP] Token fetch failed: {text}")
                result = await resp.json()
                return result.get("access_token")
