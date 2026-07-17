"""Wardress API entrypoint."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.ratelimit import enforce_ip_rate_limit
from app.routers import (
    alerts,
    apikeys,
    artifacts,
    audit,
    auth,
    health,
    imports,
    remediation,
    reports,
    settings,
    sites,
    users,
)

app = FastAPI(
    title="Wardress",
    description="Self-hosted website defacement detection and monitoring.",
    version="0.1.0",
)

# CORS locked to explicitly-configured origins (§9). The Phase 0 decision
# serves the SPA same-origin, so the default list is empty and no cross-
# origin request is permitted; set CORS_ALLOWED_ORIGINS only if the
# frontend is ever hosted elsewhere.
_cors_origins = get_settings().cors_origins()
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Per-IP rate limit (§9), applied before authentication so
    unauthenticated floods are capped too. Static asset routes are exempt
    — only the API surface is metered. Per-user limiting runs later, in
    the auth dependency."""
    if request.url.path.startswith("/api/"):
        try:
            enforce_ip_rate_limit(request)
        except StarletteHTTPException as exc:
            return JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
    return await call_next(request)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(apikeys.router)
app.include_router(audit.router)
app.include_router(sites.router)
app.include_router(imports.router)
app.include_router(remediation.router)
app.include_router(artifacts.router)
app.include_router(alerts.router)
app.include_router(settings.router)
app.include_router(settings.channels_router)
app.include_router(reports.router)


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for client-side routes
    (React Router paths like /sites/<id> must load the SPA, not 404).
    Unmatched /api/* paths stay real 404s — an API typo must never come
    back as a 200 HTML page."""

    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Starlette normalizes the path with os.path.normpath, so the
            # separator is "\" on Windows dev machines — normalize back.
            posix_path = path.replace("\\", "/")
            if exc.status_code == 404 and posix_path != "api" and not posix_path.startswith("api/"):
                return await super().get_response("index.html", scope)
            raise


# Serve the built frontend bundle when present (Docker image copies it to
# /app/static; absent in local dev where Vite's dev server proxies /api).
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", SPAStaticFiles(directory=_static_dir, html=True), name="frontend")
