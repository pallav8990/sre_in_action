from __future__ import annotations

from srehubapp.connectors.landlord_connector import LandlordConnector


class LandlordBrick:
    async def fetch_remote_get_paths(self) -> dict:
        return await LandlordConnector().fetch_filtered_openapi()

    async def proxy_get(self, path: str, params: dict, headers: dict):
        return await LandlordConnector().proxy_get(path, params, headers)