# telemetry/metrics.py
import os
from typing import Dict
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

# Parse comma-separated floats, fallback to sane web latency buckets (ms range)
def _parse_buckets(env_name: str, default):
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

def _label_fn(req, resp) -> Dict[str, str]:
    # Use templated route path to avoid high cardinality; fall back to mounted path
    path_template = getattr(req.scope.get("route"), "path", req.url.path)
    return {
        "method": req.method,
        "path": path_template,
    }

def init_metrics(app, expose_endpoint: str = "/metrics"):
    buckets = _parse_buckets("SREHUB_LATENCY_BUCKETS", _DEFAULT_LATENCY_BUCKETS)

    inst = Instrumentator(
        # Cardinality controls
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_group_untemplated=True,
        excluded_handlers={expose_endpoint, "/healthz", "/livez", "/readyz"},
        inprogress_name="srehub_inprogress_requests",
        inprogress_labels=True,
    )

    # Default FastAPI metrics: requests, latency, etc.
    inst.add(
        latency=True,
        latency_buckets=buckets,
        group_status_codes=True,
        label_fn=_label_fn,
    ).add(
        request_size=True,
        response_size=True,
        label_fn=_label_fn,
    ).add(
        inprogress=True,
        label_fn=_label_fn,
    )

    # Expose /metrics
    inst.instrument(app).expose(app, endpoint=expose_endpoint)
    return REGISTRY