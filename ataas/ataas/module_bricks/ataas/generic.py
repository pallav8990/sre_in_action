from __future__ import annotations
from typing import Any, Dict
from pydantic import BaseModel
from jsonschema import validate as json_validate, ValidationError
from fastapi import HTTPException, status
from .base import Job, JobArgs, JobResult

class DictArgs(JobArgs):
    __root__: Dict[str, Any]

class GenericAtaasJob(Job):
    ArgsModel = DictArgs

    def __init__(self, *, connector, entitlements, telemetry, queue, meta: Dict[str, Any]):
        super().__init__(connector=connector, entitlements=entitlements, telemetry=telemetry, queue=queue)
        self._meta = meta
        self.name = meta["name"]
        self.title = meta.get("title", meta["name"])
        self.description = meta.get("description", "")
        self.schema_version = str(meta.get("version", "1.0.0"))
        self._schema = meta.get("schema") or {"type": "object", "properties": {}}

    def instance_args_schema(self) -> Dict[str, Any]:
        return self._schema

    async def run(self, *, args: DictArgs, caller, correlation_id) -> JobResult:
        payload = args.__root__
        if not self.entitlements.allow(caller, self.name, payload):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "AUTHZ_DENIED")
        try:
            json_validate(instance=payload, schema=self.instance_args_schema())
        except ValidationError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"SCHEMA_MISMATCH: {e.message}")

        async with self.connector() as client:
            ataas_job_id = await client.trigger(self.name, payload, client_token=payload.get("client_token"))
        return JobResult(run_id=str(ataas_job_id), message="Enqueued", outputs={"ataasJobId": ataas_job_id})