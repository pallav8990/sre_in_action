# app.py
from fastapi import FastAPI
from telemetry.metrics import init_metrics
from routers import api_v1  # your existing router package

def create_app() -> FastAPI:
    app = FastAPI(title="SREHubApp", version="1.0")
    init_metrics(app)  # <-- one line, zero changes to routers/endpoints
    app.include_router(api_v1.router, prefix="/api/v1")
    return app

app = create_app()