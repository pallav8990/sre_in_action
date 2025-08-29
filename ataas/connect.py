# srehubapp/connectors/ataas_connector.py
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

# -----------------------------
# Exceptions
# -----------------------------
class ATAASAPIError(RuntimeError):
    def __init__(self, status: int, message: str, payload: Optional[dict] = None):
        super().__init__(f"ATAAS API error {status}: {message}")
        self.status = status
        self.message = message
        self.payload = payload or {}

class ATAASCircuitOpen(RuntimeError):
    pass


# -----------------------------
# Config (env-driven, stateless)
# -----------------------------
@dataclass(frozen=True)
class ATAASConfig:
    base_url: str
    token: Optional[str] = None              # Bearer token
    api_key: Optional[str] = None            # Optional x-api-key
    timeout_sec: float = 15.0
    connect_timeout_sec: float = 5.0

    # Retry policy
    retries: int = 3
    backoff_base: float = 0.2                # seconds
    backoff_max: float = 3.0                 # seconds
    jitter: bool = True

    # Circuit breaker
    cb_error_threshold: int = 8              # open after N consecutive failures
    cb_reset_after_sec: float = 30.0         # half-open after this cool-off

    # Optional project default
    default_project: Optional[str] = None

    @staticmethod
    def from_env() -> "ATAASConfig":
        return ATAASConfig(
            base_url=os.getenv("ATAAS_BASE_URL", "").rstrip("/"),
            token=os.getenv("ATAAS_BEARER_TOKEN"),
            api_key=os.getenv("ATAAS_API_KEY"),
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


# -----------------------------
# Low-boil circuit breaker
# -----------------------------
class _Circuit:
    def __init__(self, threshold: int, reset_after: float) -> None:
        self.threshold = threshold
        self.reset_after = reset_after
        self.failures = 0
        self.opened_at: Optional[float] = None

    def on_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.time()

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        # half-open after cool-off
        return (time.time() - self.opened_at) >= self.reset_after

    def maybe_close_after_probe(self, success: bool) -> None:
        if self.opened_at is None:
            return
        if success:
            # Close circuit after a successful probe
            self.on_success()
        else:
            # Reopen immediately
            self.opened_at = time.time()


# -----------------------------
# Connector
# -----------------------------
class ATAASConnector:
    """
    Lightweight async client with retries, timeouts, and a simple circuit breaker.

    Usage:
        async with ATAASConnector() as ataas:
            jobs = await ataas.list_jobs(project="platform-prod")
            run_id = await ataas.trigger("db-backup", payload={...}, client_token="idem-123")
            status = await ataas.status(run_id)
    """

    def __init__(self, config: Optional[ATAASConfig] = None) -> None:
        self.config = config or ATAASConfig.from_env()
        if not self.config.base_url:
            raise ValueError("ATAAS_BASE_URL must be set")
        self._client: Optional[httpx.AsyncClient] = None
        self._circuit = _Circuit(
            threshold=self.config.cb_error_threshold,
            reset_after=self.config.cb_reset_after_sec,
        )

    async def __aenter__(self) -> "ATAASConnector":
        headers = {}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=headers,
            timeout=httpx.Timeout(
                self.config.timeout_sec,
                connect=self.config.connect_timeout_sec,
            ),
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()
        self._client = None

    # ---------- Public API ----------

    async def list_jobs(self, project: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns a list of job dicts: [{"name":"db-backup","version":"1.1.0","tags":["stable"],"schema":{...}}, ...]
        """
        project = project or self.config.default_project
        if not project:
            raise ValueError("project must be provided (env SREHUB_ATAAS_PROJECT or param)")

        path = f"/api/v1/projects/{project}/jobs"
        resp = await self._request("GET", path)
        if not isinstance(resp, list):
            raise ATAASAPIError(500, "Unexpected response for list_jobs", payload={"body": resp})
        return resp

    async def trigger(
        self,
        job: str,
        payload: Dict[str, Any],
        *,
        client_token: Optional[str] = None,   # use to ask ATAAS to dedupe idempotently
    ) -> str:
        """
        Triggers a job run and returns a run_id from ATAAS.
        """
        path = f"/api/v1/jobs/{job}/runs"
        headers = {"Idempotency-Key": client_token} if client_token else None
        resp = await self._request("POST", path, json=payload, headers=headers)
        # Expecting {"run_id": "..."} or {"id": "..."}
        run_id = resp.get("run_id") or resp.get("id")
        if not run_id:
            raise ATAASAPIError(500, "No run_id in trigger response", payload={"body": resp})
        return str(run_id)

    async def status(self, run_id: str) -> Dict[str, Any]:
        """
        Returns the status dict for a previously triggered run.
        """
        path = f"/api/v1/runs/{run_id}"
        resp = await self._request("GET", path)
        if not isinstance(resp, dict):
            raise ATAASAPIError(500, "Unexpected response for status", payload={"body": resp})
        return resp

    # ---------- Internals ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Any:
        """
        Single entry for HTTP calls with retry + backoff + circuit breaker.
        """
        if self._client is None:
            raise RuntimeError("Connector not started. Use 'async with ATAASConnector() as c:'")

        # Circuit check
        if not self._circuit.allow():
            raise ATAASCircuitOpen("Circuit open for ATAAS; backing off")

        attempt = 0
        last_exc: Optional[Exception] = None
        # include auth headers supplied at client creation; merge with per-call headers
        merged_headers = dict(self._client.headers)
        if headers:
            merged_headers.update(headers)

        while attempt <= self.config.retries:
            probe_mode = (attempt > 0 and not self._circuit.allow())
            try:
                resp = await self._client.request(method, path, json=json, headers=merged_headers)
                if 200 <= resp.status_code < 300:
                    self._circuit.maybe_close_after_probe(True)
                    self._circuit.on_success()
                    if resp.headers.get("content-type", "").startswith("application/json"):
                        return resp.json()
                    # fall back to text
                    return {"text": resp.text}

                # Non-2xx
                body = _safe_json(resp)
                # Consider 5xx and some 429 as retryable
                if resp.status_code >= 500 or resp.status_code in (408, 429):
                    self._circuit.on_failure()
                    await self._sleep_backoff(attempt)
                    attempt += 1
                    continue

                # 4xx non-retryable
                self._circuit.maybe_close_after_probe(False)
                raise ATAASAPIError(resp.status_code, body.get("error") or resp.text, payload=body)

            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                last_exc = e
                self._circuit.on_failure()
                await self._sleep_backoff(attempt)
                attempt += 1
                continue

            except Exception as e:
                last_exc = e
                # unexpected; don't assume retryable unless network-ish
                self._circuit.on_failure()
                await self._sleep_backoff(attempt)
                attempt += 1
                continue

        # Retries exhausted
        if last_exc:
            raise last_exc
        raise ATAASAPIError(503, "ATAAS unavailable after retries")

    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.config.backoff_base * (2 ** attempt)
        delay = min(base, self.config.backoff_max)
        if self.config.jitter:
            delay = delay * (0.5 + random.random() * 0.75)  # 0.5x–1.25x jitter
        await asyncio.sleep(delay)


def _safe_json(resp: httpx.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except Exception:
        return {"text": resp.text}


# --------------------------------
# Factory: keep your existing pattern
# --------------------------------
@asynccontextmanager
async def make_ataas_connector(config: Optional[ATAASConfig] = None) -> AsyncIterator[ATAASConnector]:
    """
    `async with make_ataas_connector() as client: ...`
    aligns with the pattern you've already been using in module bricks.
    """
    conn = ATAASConnector(config=config)
    try:
        async with conn as started:
            yield started
    finally:
        # context manager handles close
        pass