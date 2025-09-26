from __future__ import annotations
from typing import Dict, Iterable, Type
from .base import Job

class JobRegistry:
    def __init__(self):
        self._jobs: Dict[str, Type[Job]] = {}

    def register(self, job_cls: Type[Job]):
        name = job_cls.job_name()
        if not getattr(job_cls, "enabled", True):
            return job_cls
        if name in self._jobs:
            raise ValueError(f"Duplicate job name: {name}")
        self._jobs[name] = job_cls
        return job_cls

    def get(self, name: str) -> Type[Job]:
        return self._jobs[name]

    def all(self) -> Iterable[Type[Job]]:
        return self._jobs.values()

registry = JobRegistry()

def job(cls: Type[Job]) -> Type[Job]:
    return registry.register(cls)