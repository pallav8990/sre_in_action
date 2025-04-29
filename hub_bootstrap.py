
import os

# List of folders to create
folders = [
    "srehubapp/app/config",
    "srehubapp/app/connectors",
    "srehubapp/app/processors",
    "srehubapp/app/caching",
    "srehubapp/app/routers",
    "srehubapp/app/models",
    "srehubapp/app/observability",
    "srehubapp/app/utils",
    "srehubapp/app/healthcheck",
    "srehubapp/tests",
    "srehubapp/docs",
    "srehubapp/scripts",
]

# Files to create with optional starter content
files = {
    "srehubapp/app/__init__.py": "",
    "srehubapp/app/main.py": """
from fastapi import FastAPI

app = FastAPI()

@app.get("/healthz")
def health_check():
    return {"status": "ok"}
""",
    "srehubapp/app/config/settings.py": """
import os

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
""",
    "srehubapp/app/caching/redis_cache.py": """
import redis
import json
import os

redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=0
)

def cacheable(ttl=300):
    def decorator(func):
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{args}:{kwargs}"
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached.decode('utf-8'))
            result = func(*args, **kwargs)
            redis_client.setex(cache_key, ttl, json.dumps(result))
            return result
        return wrapper
    return decorator
""",
    "srehubapp/requirements.txt": """
fastapi
uvicorn
redis
httpx
prometheus_client
structlog
python-dotenv
tenacity
pybreaker
""",
    "srehubapp/README.md": "# SREHubApp Starter Project\n\nReady to build.",
    "srehubapp/.gitignore": "__pycache__/\n.env\n*.pyc\n",
    "srehubapp/scripts/deploy_redis.yaml": """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:6.2
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  ports:
  - port: 6379
  selector:
    app: redis
""",
    "srehubapp/scripts/deploy_srehubapp.yaml": """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: srehubapp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: srehubapp
  template:
    metadata:
      labels:
        app: srehubapp
    spec:
      containers:
      - name: srehubapp
        image: yourregistry/srehubapp:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: srehubapp-config
---
apiVersion: v1
kind: Service
metadata:
  name: srehubapp
spec:
  ports:
  - port: 8000
  selector:
    app: srehubapp
""",
}

def create_structure():
    for folder in folders:
        os.makedirs(folder, exist_ok=True)
        print(f"Created folder: {folder}")

    for filepath, content in files.items():
        with open(filepath, "w") as f:
            f.write(content.strip())
        print(f"Created file: {filepath}")

if __name__ == "__main__":
    create_structure()
