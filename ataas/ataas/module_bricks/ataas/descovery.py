from __future__ import annotations
import fnmatch, os
from typing import Any, Dict, List
from ...connectors.ataas_connector import make_ataas_connector

def _split_env(name: str) -> List[str]:
    v = os.getenv(name, "").strip()
    return [s.strip() for s in v.split(",") if s.strip()]

def _allowed(name: str, tags: List[str], allow: List[str], deny: List[str], require_tags: List[str]) -> bool:
    if allow and not any(fnmatch.fnmatch(name, pat) for pat in allow): return False
    if any(fnmatch.fnmatch(name, pat) for pat in deny): return False
    if require_tags and not set(require_tags).issubset(set(tags or [])): return False
    return True

async def discover_filtered_jobs() -> List[Dict[str, Any]]:
    project = os.getenv("SREHUB_ATAAS_PROJECT", "default")
    allow = _split_env("SREHUB_ATAAS_ALLOW")
    deny = _split_env("SREHUB_ATAAS_DENY")
    require_tags = _split_env("SREHUB_ATAAS_REQUIRE_TAGS")
    async with make_ataas_connector() as c:
        catalog = await c.list_jobs(project=project)
    # c.list_jobs returns JobCatalogItem models → coerce to dict
    items = [j.model_dump() for j in catalog]
    return [j for j in items if _allowed(j.get("name",""), j.get("tags", []), allow, deny, require_tags)]