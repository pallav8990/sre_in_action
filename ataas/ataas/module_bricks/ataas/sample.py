from __future__ import annotations
from pydantic import Field
from .base import Job, JobArgs, JobResult
from .registry import job
from ...connectors.ataas_connector import make_ataas_connector

class DbBackupArgs(JobArgs):
    cluster: str = Field(..., description="OpenShift cluster name")
    namespace: str = Field(..., description="K8s namespace")
    retention_days: int = Field(7, ge=1, le=60)
    dry_run: bool = False

@job
class DbBackup(Job):
    name = "db-backup"
    title = "Database Backup"
    description = "Trigger DB backup through ATAAS"
    ArgsModel = DbBackupArgs

    async def run(self, *, args: DbBackupArgs, caller, correlation_id) -> JobResult:
        payload = args.model_dump() | {"correlation_id": correlation_id}
        async with make_ataas_connector() as c:
            run_id = await c.trigger(self.job_name(), payload, client_token=f"{self.job_name()}:{hash(str(payload))}")
        return JobResult(run_id=str(run_id), message="Enqueued")