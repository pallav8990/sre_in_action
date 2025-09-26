from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any, Dict, Optional

class JobArgs(BaseModel): ...

class JobResult(BaseModel):
    run_id: str
    message: str
    outputs: Optional[Dict[str, Any]] = None

class Job(ABC):
    name: str = ""              # defaults from class name if empty
    title: str = ""
    description: str = ""
    schema_version: str = "1.0.0"
    enabled: bool = True
    ArgsModel = JobArgs

    def __init__(self, *, connector, entitlements, telemetry=None, queue=None):
        self.connector = connector
        self.entitlements = entitlements
        self.telemetry = telemetry
        self.queue = queue

    @classmethod
    def job_name(cls) -> str:
        if cls.name: return cls.name
        import re
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\\1-\\2", cls.__name__)
        return re.sub("([a-z0-9])([A-Z])", r"\\1-\\2", s1).lower()

    @classmethod
    def args_schema(cls) -> Dict[str, Any]:
        return cls.ArgsModel.model_json_schema()

    @abstractmethod
    async def run(self, *, args: JobArgs, caller: Dict[str, Any], correlation_id: str) -> JobResult:
        ...