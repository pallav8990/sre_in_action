from typing import Any, Dict, Tuple, Optional, get_args
from fastapi import Depends, Request
from pydantic import BaseModel, Field, create_model
from fastapi import HTTPException

# crude OAS2 type → python type mapping
def _py_type(p: Dict[str, Any]):
    t = p.get("type", "string")
    fmt = p.get("format")
    if t == "integer":
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    # arrays of simple types
    if t == "array":
        item = p.get("items", {})
        it = _py_type(item)
        from typing import List
        return List[it]  # type: ignore
    return str  # default

def _field_default(p: Dict[str, Any]):
    if "default" in p:
        return p["default"]
    return ... if p.get("required") else None

def build_param_model_from_oas(parameters: Optional[list], *, name: str) -> Optional[type[BaseModel]]:
    """
    Build a Pydantic model for query params from OAS2 'parameters' (only 'in'=='query' considered).
    Returns None if no query params are present.
    """
    if not parameters:
        return None

    fields: Dict[str, Tuple[type, Field]] = {}
    for par in parameters:
        if par.get("in") != "query":
            continue
        py_t = _py_type(par)
        default = _field_default(par)
        kwargs: Dict[str, Any] = {"description": par.get("description")}
        if "enum" in par:
            # keep enum text in docs; validation left to value set
            kwargs["json_schema_extra"] = {"enum": par["enum"]}
        fields[par["name"]] = (py_t, Field(default, **kwargs))

    if not fields:
        return None

    model = create_model(f"{name}Params", **fields)  # type: ignore
    return model