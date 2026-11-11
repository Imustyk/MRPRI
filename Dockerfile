
# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir \
    fastapi==0.115.6 \
    "uvicorn[standard]==0.34.0" \
    pymongo==4.18.2 \
    numpy==2.2.1 \
    pandas==2.2.3 \
    networkx==3.4.2

COPY backend ./backend
COPY src ./src
COPY --from=frontend /ui/dist ./public

RUN mkdir -p data/processed data/workspace \
    results/tables results/mongo

RUN cat > /app/serve.py <<'PY'
import os
import base64
import secrets

from fastapi import Request, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from backend.app.main import app

@app.middleware("http")
async def demo_security(request: Request, call_next):
    user = os.getenv("DEMO_USER", "")
    password = os.getenv("DEMO_PASSWORD", "")

    if not user or not password:
        return Response("Demo credentials missing", status_code=503)

    authorization = request.headers.get("authorization", "")
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "basic":
            raise ValueError("Not Basic auth")
        supplied = base64.b64decode(
            token, validate=True
        ).decode("utf-8")
    except (ValueError, UnicodeError):
        supplied = ""

    if not secrets.compare_digest(
        supplied, f"{user}:{password}"
    ):
        return Response(
            "Authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="AchiziLens Demo"'},
        )

    if request.url.path == "/api/pipeline/run":
        return Response("Disabled in demo", status_code=403)

    return await call_next(request)

app.mount(
    "/assets",
    StaticFiles(directory="/app/public/assets"),
    name="assets"
)

@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    return FileResponse("/app/public/index.html")
PY

EXPOSE 8080

CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8080"]
