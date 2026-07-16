"""App-level routing tests: health endpoint and the SPA static fallback.

The SPA mount only activates when a built bundle exists, so these tests
build a throwaway static dir and mount SPAStaticFiles on a scratch app.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.main import SPAStaticFiles, app


async def test_health(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_unknown_api_route_is_404_json(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


@pytest.fixture
async def spa_client(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>SPA</body></html>", encoding="utf-8")
    (tmp_path / "asset.js").write_text("console.log(1)", encoding="utf-8")

    scratch = FastAPI()

    @scratch.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    scratch.mount("/", SPAStaticFiles(directory=tmp_path, html=True), name="frontend")
    transport = httpx.ASGITransport(app=scratch)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_spa_serves_real_files(spa_client: httpx.AsyncClient) -> None:
    assert (await spa_client.get("/asset.js")).status_code == 200


async def test_spa_falls_back_to_index_for_client_routes(spa_client: httpx.AsyncClient) -> None:
    resp = await spa_client.get("/sites/1234")
    assert resp.status_code == 200
    assert "SPA" in resp.text


async def test_spa_does_not_swallow_api_404(spa_client: httpx.AsyncClient) -> None:
    """A typo'd API path must be a real 404, never a 200 HTML page — an
    HTML body where the client expects JSON masks bugs."""
    resp = await spa_client.get("/api/typo")
    assert resp.status_code == 404


def test_openapi_lists_phase1_endpoints() -> None:
    paths = app.openapi()["paths"]
    for expected in (
        "/api/health",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/sites",
        "/api/sites/{site_id}",
        "/api/sites/{site_id}/rebaseline",
        "/api/sites/{site_id}/scan-now",
        "/api/sites/{site_id}/scans",
        "/api/artifacts/baselines/{baseline_id}/screenshot",
        "/api/artifacts/scans/{scan_id}/screenshot",
    ):
        assert expected in paths, f"{expected} missing from OpenAPI schema"
