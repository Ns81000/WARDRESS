"""Wardress API entrypoint."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.routers import artifacts, auth, sites

app = FastAPI(
    title="Wardress",
    description="Self-hosted website defacement detection and monitoring.",
    version="0.1.0",
)


@app.get("/api/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Liveness probe. Extended in Phase 5 with queue depth, scan latency,
    DB size, and uptime per the master prompt §7."""
    return {"status": "ok", "service": "wardress-api"}


app.include_router(auth.router)
app.include_router(sites.router)
app.include_router(artifacts.router)


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
