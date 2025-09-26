diagrams.

---

## 1. Startup – ATAAS Auto-discovery → Swagger Routes

```mermaid
sequenceDiagram
    autonumber
    participant U as Process Start
    participant APP as SREHubApp (FastAPI)
    participant DISC as Discovery (module_bricks/ataas/discovery.py)
    participant CONN as ATAASConnector (connectors/)
    participant AUTH as ApiKeyAuth (auth/auth_base.py)
    participant ATAAS as ATAAS API
    participant ROUTER as ataas router (api/v1/routers/ataas.py)
    participant SWAG as Swagger/OpenAPI

    U->>APP: Load env (ATAAS_BASE_URL, ATAAS_API_KEY, SREHUB_ATAAS_PROJECT, filters)
    APP->>DISC: startup(): discover_filtered_jobs()
    DISC->>CONN: make_ataas_connector()  (inject AuthStrategy)
    CONN->>AUTH: headers()  (x-api-key)
    CONN->>ATAAS: GET /api/v1/projects/{project}/jobs\n(x-api-key)
    ATAAS-->>CONN: 200 OK [job catalog + schemas]
    CONN-->>DISC: JobCatalogItem[]
    DISC-->>APP: filtered list (allow/deny/tags)
    APP->>ROUTER: build per-job Pydantic models (from code or schema)
    ROUTER->>ROUTER: register POST /jobs/{job}/runs (per job)
    ROUTER->>SWAG: OpenAPI generated from routes
    SWAG-->>U: Swagger shows one endpoint per job with typed body
```

---

## 2. Runtime – Request Flow (API → Brick → Connector → Downstream)

```mermaid
sequenceDiagram
    autonumber
    box rgba(240,240,240,0.5) Client
      participant CLI as Client / UI / CURL
    end
    box rgba(240,240,255,0.5) SREHubApp
      participant API as FastAPI Router (api/v1/…)
      participant AUTHZ as Auth & Entitlements (middleware/deps)
      participant BRICK as Module Brick (domain logic)
      participant CONN as Connector (connectors/)
      participant STRAT as AuthStrategy (auth/auth_base.py)
    end
    box rgba(255,245,230,0.5) Downstreams
      participant ATAAS as ATAAS
      participant JF as JFrog
      participant LL as Landlord
      participant SP as Splunk
    end

    CLI->>API: POST /api/v1/{domain}/... (JSON body)
    API->>AUTHZ: authenticate + authorize (Ping/entitlements)
    AUTHZ-->>API: ok (caller ctx)
    API->>BRICK: call domain operation with typed args
    BRICK->>CONN: make_*_connector()
    CONN->>STRAT: headers()
    alt ATAAS job trigger
      BRICK->>CONN: trigger(job,payload)
      CONN->>ATAAS: POST /jobs/{job}/runs
      ATAAS-->>CONN: 202 {run_id}
    else JFrog op
      BRICK->>CONN: deleteOldImages()
      CONN->>JF: DELETE /api/...
      JF-->>CONN: 200 {summary}
    else Landlord op
      BRICK->>CONN: assignTenant()
      CONN->>LL: POST /tenancy/assign
      LL-->>CONN: 200 {ticketId}
    else Splunk query
      BRICK->>CONN: search(query)
      CONN->>SP: POST /services/search/jobs
      SP-->>CONN: 200 {results}
    end
    CONN-->>BRICK: response
    BRICK-->>API: JobResult / data
    API-->>CLI: JSON (run_id / outputs)
```

---

## 3. Error & Retry Path (Connector-level with Circuit Breaker)

```mermaid
sequenceDiagram
    autonumber
    participant BRICK as Module Brick
    participant CONN as Connector
    participant STRAT as AuthStrategy
    participant DS as Downstream Service

    BRICK->>CONN: request(method,path,json)
    CONN->>STRAT: headers()
    loop up to N retries
        CONN->>DS: HTTP request
        alt 5xx/timeout/429
            DS-->>CONN: error
            CONN->>CONN: backoff + maybe open circuit
        else 2xx
            DS-->>CONN: success
            CONN->>CONN: reset failures
            CONN-->>BRICK: return JSON
            break
        end
    end
    alt exhausted retries or circuit open
        CONN-->>BRICK: raise APIError/CircuitOpen
        BRICK-->>BRICK: map to uniform error
    end
```
