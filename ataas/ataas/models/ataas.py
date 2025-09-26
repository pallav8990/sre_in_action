from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class JobCatalogItem(BaseModel):
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    schema: Optional[Dict[str, Any]] = None

class TriggerResponse(BaseModel):
    run_id: str

RunState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]

class RunStatus(BaseModel):
    run_id: str
    job: Optional[str] = None
    state: RunState
    progress: Optional[int] = None
    outputs: Optional[Dict[str, Any]] = None
    correlation_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None