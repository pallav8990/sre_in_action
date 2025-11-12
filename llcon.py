from __future__ import annotations

import os
import httpx


class LandlordConnector:
    BASE_URL = os.getenv("LANDLORD_BASE_URL", "http://localhost:8080")

    async def get_client(self) -> httpx.AsyncClient:
        # TODO: replace token retrieval with your real auth flow
        token = os.getenv("LANDLORD_TOKEN", "")
        headers = {
            "Authorization": f"Bearer {token}" if token else "",
            "accept": "application/json",
        }
        return httpx.AsyncClient(base_url=self.BASE_URL, headers=headers, verify=False)

    async def fetch_filtered_openapi(self) -> dict:
        """
        Fetch landlord's OpenAPI (Swagger 2.0-style) and keep only GET ops.
        Returns: {"paths": { "/foo": {"get": {...}}, ... }}
        """
        async with await self.get_client() as client:
            # Adjust if your upstream serves it elsewhere
            resp = await client.get("/swagger/doc.json", follow_redirects=True)
            resp.raise_for_status()
            spec = resp.json()

        filtered_paths: dict = {}
        for path, methods in spec.get("paths", {}).items():
            get_method = (methods or {}).get("get")
            if get_method:
                filtered_paths[path] = {"get": get_method}

        return {"paths": filtered_paths}

    async def proxy_get(self, path: str, params: dict, headers: dict) -> dict:
        """
        Proxy a GET to upstream `/api/v1/{path}` with provided params/headers.
        """
        async with await self.get_client() as client:
            url = f"/api/v1/{path.lstrip('/')}"
            resp = await client.get(url, params=params, headers=headers, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()