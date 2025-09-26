from fastapi import FastAPI
from .api.v1.routers.ataas import ataas_router

app = FastAPI(title="SREHubApp")
app.include_router(ataas_router)

# add other routers here as needed