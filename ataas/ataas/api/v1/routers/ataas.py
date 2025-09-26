from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, create_model
from typing import Any, Dict, Optional, Tuple, Type

from ...module_bricks.ataas.bootstrap import build_catalog
from ...module_bricks.ataas.registry import registry as code_registry
from ...module_bricks.ataas.base import Job
from ...connectors.ataas_connector import make_ataas_connector

ataas_router = APIRouter(prefix="/api/v1/ataas", tags=["ataas"])

# AuthZ stub — replace with your real dependency
async def require_authz():
    return {"user": "demo", "tenant": "default"}

class Entitlements:
    def allow(self, caller, job_name: str, args: dict) -> bool:
        return True
entitlements = Entitlements()

# basic JSON Schema → Pydantic field mapper
PYD_TYPES = {
    "string": (str, ...),
    "integer": (int, ...),
    "number": (float, ...),
    "boolean": (bool, ...),
    "object": (dict, ...),
    "array": (list, ...),
}
def _field_from_schema(name: str, prop: Dict[str, Any], required: bool):
    t = prop.get("type", "string"); base, default = PYD_TYPES.get(t, (str, ...))
    desc = prop.get("description"); ex = prop.get("example")
    if not required: default = None
    return ((Optional[base] if not required else base),
            Field(default, description=desc, examples=[ex] if ex is not None else None))

def model_from_jsonschema(job_name: str, schema: Dict[str, Any]) -> Type[BaseModel]:
    props: Dict[str, Any] = schema.get("properties", {})
    req = set(schema.get("required", []))
    fields = {k: _field_from_schema(k, v, k in req) for k, v in props.items()}
    return create_model(f"{job_name.title().replace('-','_')}Args", **fields)  # type: ignore

_CODE_JOBS: Dict[str, Type[Job]] = {}
_DYNAMIC_FACTORIES: Dict[str, callable] = {}

def _add_job_route(router: APIRouter, job_name: str, ArgsModel: Type[BaseModel], JobImpl: Type[Job] | callable):
    async def trigger(
        args: ArgsModel,
        bt: BackgroundTasks,
        caller=Depends(require_authz),
    ):
        payload = args.model_dump()
        if not entitlements.allow(caller, job_name, payload):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "AUTHZ_DENIED")

        job_obj = JobImpl(connector=make_ataas_connector, entitlements=entitlements, telemetry=None, queue=bt) \
                  if isinstance(JobImpl, type) and issubclass(JobImpl, Job) else JobImpl()

        res = await job_obj.run(args=args, caller=caller, correlation_id="auto")
        return {"run_id": res.run_id, "message": res.message, "outputs": res.outputs}

    route = APIRoute(
        path=f"/jobs/{job_name}/runs",
        endpoint=trigger,
        methods=["POST"],
        name=f"run_{job_name}",
        response_model=dict,
        status_code=202,
        summary=f"Run {job_name}",
        description=f"Trigger the '{job_name}' ATAAS job.",
    )
    router.routes.append(route)

@ataas_router.on_event("startup")
async def startup():
    # Ensure code jobs are imported so @job decorator runs (import your module that defines jobs)
    try:
        from ...module_bricks.ataas import examples  # noqa: F401
    except Exception:
        pass

    global _CODE_JOBS, _DYNAMIC_FACTORIES
    _CODE_JOBS, _DYNAMIC_FACTORIES = await build_catalog()

    # Register routes for code jobs
    for JobCls in _CODE_JOBS.values():
        if not getattr(JobCls, "enabled", True): continue
        _add_job_route(ataas_router, JobCls.job_name(), JobCls.ArgsModel, JobCls)

    # Register routes for discovered jobs (generic)
    for name, factory in _DYNAMIC_FACTORIES.items():
        inst = factory()
        schema = getattr(inst, "instance_args_schema", lambda: {"type":"object","properties":{}})()
        ArgsModel = model_from_jsonschema(name, schema)
        _add_job_route(ataas_router, name, ArgsModel, factory)

@ataas_router.get("/jobs")
async def list_jobs(caller=Depends(require_authz)):
    code = [{
        "name": J.job_name(),
        "title": getattr(J, "title", J.job_name()),
        "description": getattr(J, "description", ""),
        "schemaVersion": getattr(J, "schema_version", "1.0.0"),
        "source": "code"
    } for J in _CODE_JOBS.values()]
    dyn = [{"name": n, "title": n, "description": "", "schemaVersion": "from-ataas", "source": "ataas"}
           for n in _DYNAMIC_FACTORIES.keys()]
    return code + dyn

@ataas_router.get("/jobs/{job_name}")
async def job_meta(job_name: str, caller=Depends(require_authz)):
    if job_name in _CODE_JOBS:
        J = _CODE_JOBS[job_name]
        return {"name": J.job_name(), "title": getattr(J,"title",J.job_name()), "description": getattr(J,"description",""),
                "schemaVersion": getattr(J,"schema_version","1.0.0"), "argsSchema": J.args_schema(), "source":"code"}
    if job_name in _DYNAMIC_FACTORIES:
        inst = _DYNAMIC_FACTORIES[job_name]()
        return {"name": job_name, "title": getattr(inst,"title",job_name), "description": getattr(inst,"description",""),
                "schemaVersion": getattr(inst,"schema_version","from-ataas"), "argsSchema": inst.instance_args_schema(), "source":"ataas"}
    raise HTTPException(status.HTTP_404_NOT_FOUND, "JOB_NOT_AVAILABLE")

@ataas_router.get("/runs/{run_id}")
async def run_status(run_id: str, caller=Depends(require_authz)):
    async with make_ataas_connector() as c:
        return await c.status(run_id)