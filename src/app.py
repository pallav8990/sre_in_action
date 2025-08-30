from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
import os

from log_config import setup_logger, set_log_level, LOGGER_NAME
from logger import log_execution


# Initialize logging from repo's YAML. Fallback to local default if missing.
def _init_logging():
	# Try common paths for logger config
	candidates = [
		os.getenv("LOG_CONFIG_PATH"),
		os.path.join(os.getcwd(), "log_config.yaml"),
		os.path.join(os.getcwd(), "config", "logger.yaml"),
		os.path.join(os.path.dirname(os.getcwd()), "log_config.yaml"),
	]
	for path in [p for p in candidates if p]:
		if os.path.exists(path):
			try:
				setup_logger(path)
				break
			except Exception:
				# If setup fails, continue to default
				pass
	# Ensure a logger exists regardless
	logger = logging.getLogger(LOGGER_NAME)
	if not logger.handlers:
		logging.basicConfig(level=logging.INFO)
	return logger


logger = _init_logging()

app = FastAPI(title="SRE Hub API", version="0.1.0")


class LogLevelRequest(BaseModel):
	level: str


@app.get("/healthz", tags=["ops"])  # Kubernetes-friendly health endpoint
@log_execution(logger)
def healthz():
	return {"status": "ok"}


@app.get("/readyz", tags=["ops"])  # Placeholder for readiness checks
@log_execution(logger)
def readyz():
	# Add checks like DB, cache, dependencies here
	return {"status": "ready"}


@app.post("/config/log-level", tags=["ops"])  # Dynamic log level
@log_execution(logger)
def update_log_level(payload: LogLevelRequest):
	try:
		set_log_level(payload.level)
		return {"message": f"log level set to {payload.level}"}
	except ValueError as e:
		raise HTTPException(status_code=400, detail=str(e))


@app.get("/", tags=["default"])  # Simple landing route
@log_execution(logger)
def root():
	return {"service": app.title, "version": app.version}

