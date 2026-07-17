# Wardress `app` image — FastAPI API + built frontend static files.
# Follows the official Astral uv Docker pattern (docs-cache/uv-docker.html):
# uv binary copied from the pinned distroless image, dependency layer
# installed before source copy for maximal layer caching.

# --- Stage 1: build the frontend ---
FROM node:22-alpine AS frontend-build
WORKDIR /build
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ .
RUN pnpm build

# --- Stage 2: Python runtime ---
FROM python:3.12-slim-trixie AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.9.2 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependency layer — only invalidated when the lockfile changes
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Project source
COPY backend/ .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Frontend static bundle, served by FastAPI (decision logged in PROGRESS.md)
COPY --from=frontend-build /build/dist /app/static

ENV PATH="/app/.venv/bin:$PATH"

# curl for the compose healthcheck; Pango/Cairo/GDK-PixBuf for WeasyPrint
# (PDF reports render in the API process — the Phase 0 decision keeps
# report rendering off the worker's browser pool entirely, and the API
# is where the download request lands).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
