
# SREHubApp MVP - TODO Plan

> This document provides the essential steps to build the Minimum Viable Product (MVP) for SREHubApp in a structured and efficient manner.

## TODO List

| Step | Task | Priority | Notes |
|:---|:---|:---|:---|
| 1 | Setup basic Kubernetes connector | High | Build a connector that fetches pods, nodes, events via Kubernetes API |
| 2 | Add JFrog Artifactory connector | High | Fetch image list, repo details (with optional Redis caching) |
| 3 | Create AquaScan connector (if needed) | Medium | Fetch CVE scan results from Aqua APIs |
| 4 | Wire routers (FastAPI) for Kubernetes and JFrog | High | Expose REST APIs `/k8s/pods`, `/jfrog/images`, etc. |
| 5 | Implement Redis Caching decorator | High | Already scaffolded — activate selectively per method |
| 6 | Integrate Prometheus Metrics | Medium | Add simple metrics like `api_request_total`, `cache_hit_total` |
| 7 | Add basic Health Check route `/healthz` | High | Already scaffolded — expand if needed |
| 8 | Setup environment configs (`ConfigMap`) | High | Manage API URLs, Redis host, thresholds via env vars |
| 9 | Create Exception Handling | High | Build clean error responses for API failures, timeouts |
| 10 | Add logging (structured using `structlog`) | Medium | Standardized logging with request ids, trace info |
| 11 | Write sample unit tests (pytest) | Medium | For Kubernetes connector, caching, routers |
| 12 | Dockerize the app (`Dockerfile`) | High | Already scaffolded — just build image |
| 13 | Deploy on Kubernetes | High | Use the provided `deploy_srehubapp.yaml` manifest |
| 14 | (Optional) Add Authentication layer | Low | API key-based or token auth if needed later |
| 15 | (Optional) Setup CI/CD Pipeline | Medium | GitHub Actions or GitLab for auto-deployment |

## MVP Delivery Goals

> **At the end of MVP**, SREHubApp should be able to:
> - Connect live to Kubernetes, JFrog, and optionally AquaScan.
> - Expose REST APIs for querying platform state.
> - Cache intelligently (where needed) using Redis.
> - Export lightweight metrics to Prometheus.
> - Be stateless, modular, and Kubernetes deployable.

## MVP Visual Flow

```
[ User/API Client ]
        |
    (calls)
        |
    [ SREHubApp REST API ]
        |
    (check Redis cache, if configured)
        |
    (if miss)
        |
    [ Live API call to Downstream Systems ]
        |
    (return processed response)
```

## MVP Timeline Suggestion

| Phase | Task | Estimated Time |
|:---|:---|:---|
| Phase 1 | Basic Connectors + Routers + Configs | 2–3 days |
| Phase 2 | Caching Layer + Health Check + Metrics | 1–2 days |
| Phase 3 | Testing + Logging + Deployment | 2 days |
| **Total** | **Working MVP** | **~1 week** |

---

# Key Takeaway

> Start lean. Ship fast. Extend smartly.