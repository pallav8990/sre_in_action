from __future__ import annotations
from typing import Dict, Type, Callable
from .registry import registry
from .generic import GenericAtaasJob
from .discovery import discover_filtered_jobs
from ...connectors.ataas_connector import make_ataas_connector

def _code_jobs_map():
    return {J.job_name(): J for J in registry.all() if getattr(J, "enabled", True)}

class SimpleEntitlements:
    def allow(self, caller, job_name: str, args: dict) -> bool:
        return True

async def build_catalog():
    """
    Returns:
      - code_jobs: Dict[name, Type[Job]]
      - dynamic_factories: Dict[name, Callable[[], GenericAtaasJob]]
    """
    code_jobs = _code_jobs_map()
    discovered = await discover_filtered_jobs()

    factories: Dict[str, Callable[[], GenericAtaasJob]] = {}
    for meta in discovered:
        name = meta["name"]
        if name in code_jobs:
            continue  # prefer code job override
        def factory(meta=meta):
            return GenericAtaasJob(
                connector=make_ataas_connector,
                entitlements=SimpleEntitlements(),
                telemetry=None,
                queue=None,
                meta=meta
            )
        factories[name] = factory
    return code_jobs, factories