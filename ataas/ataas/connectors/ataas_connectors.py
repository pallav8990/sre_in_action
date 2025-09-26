from __future__ import annotations

import asyncio, os, random, time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from ..auth.auth_base import AuthStrategy, auth_from_env
from ..models.ataas import JobCatalogItem, TriggerResponse, RunStatus

class ATAASAPIError(RuntimeError):
    def __init__(self, status: int, message: str, payload: Optional[dict] = None):
        super().__init__(f"ATAAS API error {status}: {message}")
        self.status, self.message, self.payload = status, message, payload or {}

class ATAASCircuitOpen(RuntimeError): pass

@dataclass(frozen=True)
class ATAASConfig:
    base_url: str
    timeout_sec: float = 15.0
    connect_timeout_sec: float = 5.0
    retries: int = 3
    backoff_base: float = 0.2
    backoff_max: float = 3.0
    jitter: bool = True
    cb_error_threshold: int = 8
    cb_reset_after_sec: float = 30.0
    default_project: Optional[str] = None

    @staticmethod
    def from_env() -> "ATAASConfig":
        return ATAASConfig(
            base_url=os.getenv("ATAAS_BASE_URL", "").rstrip("/"),
            timeout_sec=float(os.getenv("ATAAS_TIMEOUT_SEC", "15")),
            connect_timeout_sec=float(os.getenv("ATAAS_CONNECT_TIMEOUT_SEC", "5")),
            retries=int(os.getenv("ATAAS_RETRIES", "3")),
            backoff_base=float(os.getenv("ATAAS_BACKOFF_BASE", "0.2")),
            backoff_max=float(os.getenv("ATAAS_BACKOFF_MAX", "3.0")),
            jitter=os.getenv("ATAAS_JITTER", "true").lower() != "false",
            cb_error_threshold=int(os.getenv("ATAAS_CB_ERROR_THRESHOLD", "8")),
            cb_reset_after_sec=float(os.getenv("ATAAS_CB_RESET_AFTER_SEC", "30")),
            default_project=os.getenv("SREHUB_ATAAS_PROJECT"),
        )

class _Circuit:
    def __init__(self, threshold: int, reset_after: float):
        self.threshold, self.reset_after = threshold, reset_after
        self.failures = 0
        self.opened_at: Optional[float] = None
    def on_success(self): self.failures, self.opened_at = 0, None
    def on_failure(self):
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.time()
    def allow(self) -> bool:
        return self.opened_at is None or (time.time() - self.opened_at) >= self.reset_after
    def maybe_close_after_probe(self, success: bool):
        if self.opened_at is None: return
        if success: self.on_success()
        else: self.opened_at = time.time()

class ATAASConnector:
    """
    Async ATAAS client delegating auth to an injected AuthStrategy.
    """
    def __init__(self, auth: AuthStrategy, config: Optional[ATAASConfig] = None):
        self.config = config or ATAASConfig.from_env()
        if not self.config.base_url:
            raise ValueError("ATAAS_BASE_URL must be set")
        self.auth = auth
        self._client: Optional[httpx.AsyncClient] = None
        self._circuit = _Circuit(self.config.cb_error_threshold, self.config.cb_reset_after_sec)

    async def __aenter__(self) -> "ATAASConnector":
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.timeout_sec, connect=self.config.connect_timeout_sec),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._client: await self._client.aclose()
        self._client = None

    # ---- Public API ----
    async def list_jobs(self, project: Optional[str] = None) -> List[JobCatalogItem]:
        project = project or self.config.default_project
        if not project:
            raise ValueError("project must be provided (env SREHUB_ATAAS_PROJECT or param)")
        raw = await self._request("GET", f"/api/v1/projects/{project}/jobs")
        if not isinstance(raw, list):
            raise ATAASAPIError(500, "Unexpected response for list_jobs", payload={"body": raw})
        return [JobCatalogItem(**item) for item in raw]

    async def trigger(self, job: str, payload: Dict[str, Any], *, client_token: Optional[str] = None) -> str:
        headers = {"Idempotency-Key": client_token} if client_token else None
        raw = await self._request("POST", f"/api/v1/jobs/{job}/runs", json=payload, headers=headers)
        if isinstance(raw, dict) and ("run_id" in raw or "id" in raw):
            return str(raw.get("run_id") or raw.get("id"))
        try:
            return TriggerResponse(**raw).run_id  # type: ignore[arg-type]
        except Exception:
            raise ATAASAPIError(500, "No run_id in trigger response", payload={"body": raw})

    async def status(self, run_id: str) -> RunStatus:
        raw = await self._request("GET", f"/api/v1/runs/{run_id}")
        if not isinstance(raw, dict):
            raise ATAASAPIError(500, "Unexpected response for status", payload={"body": raw})
        return RunStatus(**raw)

    # ---- Internals ----
    async def _request(self, method: str, path: str, *, json: Optional[dict] = None, headers: Optional[dict] = None):
        if self._client is None:
            raise RuntimeError("Connector not started. Use 'async with ATAASConnector(...) as c:'")
        if not self._circuit.allow():
            raise ATAASCircuitOpen("Circuit open for ATAAS; backing off")

        attempt, last_exc = 0, None
        while attempt <= self.config.retries:
            try:
                auth_headers = await self.auth.headers()
                merged_headers = {**auth_headers, **(headers or {})}
                resp = await self._client.request(method, path, json=json, headers=merged_headers)

                if 200 <= resp.status_code < 300:
                    self._circuit.maybe_close_after_probe(True); self._circuit.on_success()
                    return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}

                body = _safe_json(resp)
                if resp.status_code >= 500 or resp.status_code in (408, 429):
                    self._circuit.on_failure(); await self._sleep_backoff(attempt); attempt += 1; continue
                self._circuit.maybe_close_after_probe(False)
                raise ATAASAPIError(resp.status_code, body.get("error") or resp.text, payload=body)

            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                last_exc = e; self._circuit.on_failure(); await self._sleep_backoff(attempt); attempt += 1; continue
            except Exception as e:
                last_exc = e; self._circuit.on_failure(); await self._sleep_backoff(attempt); attempt += 1; continue

        if last_exc: raise last_exc
        raise ATAASAPIError(503, "ATAAS unavailable after retries")

    async def _sleep_backoff(self, attempt: int):
        base = self.config.backoff_base * (2 ** attempt)
        delay = min(base, self.config.backoff_max)
        if self.config.jitter: delay *= (0.5 + random.random() * 0.75)
        await asyncio.sleep(delay)

def _safe_json(resp: httpx.Response) -> Dict[str, Any]:
    try: return resp.json()
    except Exception: return {"text": resp.text}

# Factory: keep auth in the shared auth layer
@asynccontextmanager
async def make_ataas_connector(config: Optional[ATAASConfig] = None) -> AsyncIterator[ATAASConnector]:
    auth = auth_from_env("ATAAS")  # will produce ApiKeyAuth for ATAAS
    conn = ATAASConnector(auth=auth, config=config or ATAASConfig.from_env())
    async with conn as started:
        yield started