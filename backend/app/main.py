"""Wardress API entrypoint."""

import asyncio
import json
import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from app.ai_startup import bootstrap_catalog, bootstrap_migration
from app.config import get_settings
from app.ratelimit import enforce_ip_rate_limit
from app.routers import (
    agent,
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

logger = logging.getLogger(__name__)

_bg_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    # Migrate legacy AI settings before serving (fast, local) so the AI works
    # on the first request; refresh the models.dev catalog in the background so
    # a slow/absent network never delays startup (bundled snapshot covers it).
    await bootstrap_migration()
    task = asyncio.create_task(bootstrap_catalog())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    yield


app = FastAPI(
    title="Wardress",
    description="Self-hosted website defacement detection and monitoring.",
    version="0.1.0",
    lifespan=lifespan,
)


class RequestBodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._send_too_large(scope, receive, send)
                    return
            except ValueError:
                await self._send_too_large(scope, receive, send)
                return

        total = 0
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            total += len(body)
            if total > self.max_bytes:
                await self._send_too_large(scope, receive, send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        sent = False

        async def limited_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            # Body already delivered. Defer to the real transport instead of
            # returning a synthetic empty message: a StreamingResponse runs a
            # disconnect listener that calls receive() in a loop until it sees
            # http.disconnect, so a non-blocking stub would spin it hot and
            # starve the event loop (the stream body would never run).
            return await receive()

        await self.app(scope, limited_receive, send)

    async def _send_too_large(self, scope, receive, send) -> None:
        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
        await response(scope, receive, send)


# NOTE: middleware registration happens AFTER both classes below (see the
# ordering comment at the bottom of this file) — Starlette's add_middleware
# prepends, so the LAST registration runs FIRST (outermost).
class StrictJSONBodyMiddleware:
    """Reject NaN/Infinity numeric literals with 422 before pydantic sees
    them (Finding: "NaN/Infinity in any float field returns 500").

    Python's lenient `json.loads` accepts `NaN`/`Infinity`/`-Infinity`,
    which are NOT valid JSON. Pydantic then correctly rejects the value,
    but FastAPI's validation-error response embeds the raw input, and
    Starlette's JSONResponse renders with allow_nan=False — serializing
    that error raises ValueError and the client receives a misleading 500.
    Parsing strictly here kills the class for every JSON endpoint at once:
    a body containing non-finite constants is malformed JSON (422), the
    same verdict any strict JSON parser gives."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").decode("latin-1")
        if content_type.split(";")[0].strip().lower() != "application/json":
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            chunks.append(body)
            if not message.get("more_body", False):
                break

        raw = b"".join(chunks)
        try:
            data = json.loads(raw, parse_constant=_reject_constant)
            # Valid JSON text can STILL carry non-finite numbers via
            # overflow (`1e400` parses to inf), and pydantic's rejection of
            # such a value would crash response serialization exactly like
            # the literal form did — reject them here too.
            _ensure_finite(data)
        except (ValueError, UnicodeDecodeError):
            # Covers NaN/Infinity/-Infinity literals (routed through
            # parse_constant), overflowed non-finite floats, and ordinary
            # malformed JSON. A 422 detail keeps the shape clients already
            # handle for invalid bodies; nothing downstream ever runs.
            response = JSONResponse({"detail": "Request body is not valid JSON"}, status_code=422)
            await response(scope, receive, send)
            return

        sent = False

        async def replay_receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


def _reject_constant(value: str):  # noqa: ARG001 - signature fixed by json module
    raise ValueError(f"{value} is not valid JSON")


def _ensure_finite(node, _depth: int = 0) -> None:
    """Reject any non-finite float anywhere in a parsed JSON body (overflow
    forms like 1e400 are valid JSON text but serialize as Infinity). Depth-
    and size-capped: request bodies already passed the 1 MiB limit middleware,
    so recursion depth beyond 64 means hostile nesting, not real payloads."""
    if _depth > 64:
        raise ValueError("JSON nesting too deep")
    if isinstance(node, float) and not math.isfinite(node):
        raise ValueError("JSON numbers must be finite")
    if isinstance(node, dict):
        for value in node.values():
            _ensure_finite(value, _depth + 1)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _ensure_finite(value, _depth + 1)


# --- Middleware registration (ORDER MATTERS) ---
# Starlette's add_middleware PREPENDS: the LAST registration is the
# OUTERMOST middleware. The required chain is:
#   rate-limit -> body-size gate (413) -> strict JSON (422) -> CORS -> app.
# The @app.middleware("http") rate limiter below registers after these, so it
# ends up outermost of the three. Registering the size gate LAST puts it
# outside the strict parser, so an over-limit body stops at 413 before any
# parsing work — exactly as before the parser existed (pinned by
# test_over_limit_body_returns_413_before_parsing). The parser sits inside
# it and rejects NaN/Infinity/overflow bodies before pydantic ever runs.
app.add_middleware(StrictJSONBodyMiddleware)
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    max_bytes=get_settings().max_request_body_bytes,
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
app.include_router(settings.ai_router)
app.include_router(reports.router)
app.include_router(agent.router)


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
