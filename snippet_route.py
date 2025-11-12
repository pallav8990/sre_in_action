from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, create_model

from srehubapp.modulebricks.landlord_brick import LandlordBrick

brick = LandlordBrick()
router = APIRouter(tags=["landlord"])

# -------------------------
# Helpers: OAS2 → Pydantic
# -------------------------
def _py_type(param: Dict[str, Any]):
    t = param.get("type", "string")
    if t == "integer":
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    if t == "array":
        item = param.get("items", {})
        it = _py_type(item)
        return List[it]  # type: ignore
    return str

def _field_default(param: Dict[str, Any]):
    if "default" in param:
        return param["default"]
    return ... if param.get("required") else None

def build_param_model_from_oas(parameters: Optional[list], *, name: str) -> Optional[type[BaseModel]]:
    """
    Build a Pydantic model for **query** params from OAS2 'parameters'.
    (Path params are handled via request.path_params; we don't need to
    declare them explicitly in the function signature.)
    """
    if not parameters:
        return None

    fields: Dict[str, Tuple[type, Field]] = {}
    for par in parameters:
        if par.get("in") != "query":
            continue
        py_t = _py_type(par)
        default = _field_default(par)
        fkw: Dict[str, Any] = {"description": par.get("description")}
        if "enum" in par:
            # Keep enum visible in docs; validation can be tightened later
            fkw["json_schema_extra"] = {"enum": par["enum"]}
        fields[par["name"]] = (py_t, Field(default, **fkw))

    if not fields:
        return None

    return create_model(f"{name}Params", **fields)  # type: ignore


# -------------------------
# Explicit sample routes
# -------------------------
@router.get("/landlord/clusters")
async def get_clusters(datacenter_name: str):
    # your existing explicit endpoint
    return {"clusters_for": datacenter_name}


# ---------------------------------------
# Dynamically add GET routes from upstream
# ---------------------------------------
async def add_dynamic_routes():
    remote_spec = await brick.fetch_remote_get_paths()
    paths = remote_spec.get("paths", {})

    def make_dynamic_get(upstream_path: str, ParamModel: Optional[type[BaseModel]]):
        if ParamModel:
            async def dynamic_get(params: ParamModel = Depends(), request: Request = None):  # type: ignore
                # Query params (validated)
                q = {k: v for k, v in params.dict(exclude_none=True).items()}
                # Path params from FastAPI
                if request:
                    q.update(request.path_params or {})
                    headers = dict(request.headers)
                else:
                    headers = {}
                return await brick.proxy_get(upstream_path.lstrip("/"), q, headers)
        else:
            async def dynamic_get(request: Request):
                q = dict(request.query_params)
                q.update(request.path_params or {})
                headers = dict(request.headers)
                return await brick.proxy_get(upstream_path.lstrip("/"), q, headers)
        return dynamic_get

    for path, methods in paths.items():
        get_op = methods.get("get")
        if not get_op:
            continue

        # Preserve query parameters in docs
        ParamModel = build_param_model_from_oas(
            get_op.get("parameters"),
            name=(path.replace("/", "_") or "root")
        )

        # Mount under /landlord + upstream path (no /api/v1 here; app adds that)
        fastapi_path = "/landlord" + (path if path.startswith("/") else f"/{path}")

        # Avoid duplicates if re-run
        if fastapi_path not in [r.path for r in router.routes]:
            router.add_api_route(
                fastapi_path,
                make_dynamic_get(path, ParamModel),
                methods=["GET"],
                include_in_schema=True,
                tags=get_op.get("tags") or ["landlord"],
                summary=get_op.get("summary"),
                description=get_op.get("description"),
            )