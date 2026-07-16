"""Wardress API entrypoint.

Phase 0: a minimal application proving the container stack wires together.
Real routers (sites, scans, alerts, auth, settings) arrive in Phase 1+.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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


# Serve the built frontend bundle when present (Docker image copies it to
# /app/static; absent in local dev where Vite's dev server proxies /api).
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")
