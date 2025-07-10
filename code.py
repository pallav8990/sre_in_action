# =========================
# 📁 auth/openshift_oauth.py
# =========================
import httpx
import os
from srehubapp.utils.logger import logger

class OpenShiftOAuthClient:
    def __init__(self, cluster: str):
        self.cluster = cluster
        self.client_id = os.getenv("OCP_CLIENT_ID")
        self.client_secret = os.getenv("OCP_CLIENT_SECRET")

    def get_oauth_url(self) -> str:
        return f"https://oauth.{self.cluster}.example.com"

    async def get_access_token(self) -> str:
        token_url = f"{self.get_oauth_url()}/oauth/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, headers=headers, data=data)

        if response.status_code != 200:
            logger.error(f"[Auth] Token fetch failed for {self.cluster}: {response.text}")
            raise Exception(f"OAuth failed for cluster: {self.cluster}")

        token = response.json()["access_token"]
        logger.debug(f"[Auth] Token fetched successfully for {self.cluster}")
        return token


# ================================
# 📁 connectors/kubernetes_async.py
# ================================
from kubernetes_asyncio import client
from kubernetes_asyncio.client import Configuration, ApiClient, CoreV1Api
from srehubapp.auth.openshift_oauth import OpenShiftOAuthClient
from srehubapp.utils.logger import logger

class KubernetesAsyncConnector:
    def __init__(self, cluster: str):
        self.cluster = cluster
        self.api_client: ApiClient = None
        self.api: CoreV1Api = None

    async def __aenter__(self):
        logger.info(f"[Connector] Building API client for {self.cluster}")
        token = await OpenShiftOAuthClient(self.cluster).get_access_token()

        configuration = Configuration()
        configuration.host = f"https://api.{self.cluster}.example.com:6443"
        configuration.verify_ssl = False  # Use CA cert in production
        configuration.api_key = {"authorization": f"Bearer {token}"}
        configuration.debug = False

        self.api_client = ApiClient(configuration=configuration)
        self.api = CoreV1Api(api_client=self.api_client)
        return self.api

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.api_client:
            await self.api_client.rest_client.pool_manager.close()


# =========================
# 📁 models/openshift.py
# =========================
from pydantic import BaseModel
from typing import List

class PodItem(BaseModel):
    name: str

class PodListResponse(BaseModel):
    cluster: str
    namespace: str
    pods: List[PodItem]
    count: int


# ============================
# 📁 modulebricks/openshift_brick.py
# ============================
from srehubapp.connectors.kubernetes_async import KubernetesAsyncConnector
from srehubapp.models.openshift import PodItem, PodListResponse
from srehubapp.utils.logger import trace_latency

class OpenshiftBrick:
    @trace_latency
    async def get_pods_by_namespace(self, cluster: str, namespace: str) -> PodListResponse:
        async with KubernetesAsyncConnector(cluster=cluster) as api:
            pods = await api.list_namespaced_pod(namespace=namespace)
            items = [PodItem(name=p.metadata.name) for p in pods.items]

        return PodListResponse(
            cluster=cluster,
            namespace=namespace,
            pods=items,
            count=len(items),
        )


# =========================
# 📁 api/v1/openshift.py
# =========================
from fastapi import APIRouter
from pydantic import BaseModel
from srehubapp.modulebricks.openshift_brick import OpenshiftBrick

router = APIRouter()
brick = OpenshiftBrick()

class PodRequest(BaseModel):
    cluster: str
    namespace: str

@router.post("/openshift/get_pods_ns")
async def get_pods_ns(payload: PodRequest):
    return await brick.get_pods_by_namespace(payload.cluster, payload.namespace)


# =========================
# 📁 utils/logger.py
# =========================
import time
import logging
from functools import wraps

logger = logging.getLogger("srehubapp")

def trace_latency(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        duration = round(time.time() - start, 3)
        logger.info(f"[TRACE] {func.__name__} took {duration}s")
        return result
    return wrapper