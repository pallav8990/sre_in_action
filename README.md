# SRE Hub API

Minimal FastAPI service wired with repo logging.

## Run locally

1) Create a virtual env and install deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Start the API

```bash
uvicorn src.app:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

- GET /          -> service metadata
- GET /healthz   -> liveness
- GET /readyz    -> readiness
- POST /config/log-level {"level": "DEBUG|INFO|WARNING|ERROR|CRITICAL"}

Logs are emitted to console and `logs/srehubapp.log` per `log_config.yaml`.
