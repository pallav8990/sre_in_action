# telemetry/metrics.py
import os
from typing import List
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import (
    requests,               # total by method / handler / status
    latency,                # request duration histogram
    requests_in_progress,   # in-flight gauge
    request_size,           # bytes
    response_size,          # bytes
)

def _parse_buckets(env_name: str, default: List[float]) -> List[float]:
    raw = os.getenv(env_name, "")
    if not raw:
        return default
    try:
        return [float(x.strip()) for x in raw.split(",") if x.strip()]
    except Exception:
        return default

_DEFAULT_LATENCY_BUCKETS = [
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10
]  # seconds

def init_metrics(app, expose_endpoint: str = "/metrics"):
    buckets = _parse_buckets("SREHUB_LATENCY_BUCKETS", _DEFAULT_LATENCY_BUCKETS)

    inst = Instrumentator(
        # sensible defaults for label cardinality
        should_group_status_codes=True,     # 2xx/3xx/4xx/5xx
        should_ignore_untemplated=True,     # ignore raw/unmatched paths
        should_group_untemplated=True,      # group if not templated
        excluded_handlers={expose_endpoint, "/healthz", "/livez", "/readyz"},
        inprogress_name="srehub_inprogress_requests",
        inprogress_labels=True,
    )

    (
        inst
        .add(requests())                                # total by method/handler/status
        .add(latency(buckets=tuple(buckets)))           # histogram
        .add(requests_in_progress())                    # gauge
        .add(request_size())                            # bytes
        .add(response_size())                           # bytes
        .instrument(app)
        .expose(app, endpoint=expose_endpoint, include_in_schema=False)
    )

    return REGISTRY