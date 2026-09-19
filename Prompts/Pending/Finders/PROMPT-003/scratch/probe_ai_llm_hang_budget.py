"""PROMPT-003 Phase 4E scratch probe (preserved for reproducibility, per the
effort's scratch-probe precedent — Rule 5/10: it is not a pytest and not part
of any suite).

Measures the wall-clock cost of ONE degraded LLM call when the configured
provider accepts the connection and never answers ("hung provider"), using the
production `_REQUEST_TIMEOUT` (30 s) and Router retry settings, three passes
(Rule 18). Also records the keyless-provider fast-fail detail string.

Run:
  backend\\.venv\\Scripts\\python.exe Prompts\\Pending\\Finders\\PROMPT-003\\scratch\\probe_ai_llm_hang_budget.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[5] / "backend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://probe:probe@127.0.0.1:1/probe")
os.environ.setdefault("JWT_SECRET", "probe-secret-not-for-production-0123456789abcdef")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", "probe-encryption-key-not-for-production-0123456789")

from app.ai_config import encrypt_keys  # noqa: E402
from app.llm import _NUM_RETRIES, _REQUEST_TIMEOUT, validate_provider_call  # noqa: E402
from app.models import AiProvider  # noqa: E402


class _HangHandler(BaseHTTPRequestHandler):
    def _hang(self) -> None:
        time.sleep(300)

    do_GET = _hang
    do_POST = _hang
    do_PUT = _hang

    def log_message(self, *args) -> None:
        return


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HangHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{port}"
    print(f"hanging provider at {base_url}")
    print(
        f"production budget: timeout={_REQUEST_TIMEOUT}s num_retries={_NUM_RETRIES} "
        f"-> structural worst case per call (no fallback) = "
        f"{(1 + _NUM_RETRIES) * _REQUEST_TIMEOUT}s"
    )

    keyed = AiProvider(
        label="probe-hang",
        provider_type="openai_compatible",
        base_url=base_url,
        credentials_encrypted=encrypt_keys(["sk-probe-hang-key-0123456789"]),
    )
    keyless = AiProvider(label="probe-keyless", provider_type="openai_compatible", base_url=base_url)

    async def run() -> None:
        ok, detail = await validate_provider_call(keyless, "m")
        print(f"keyless fast-fail: ok={ok} detail={detail!r}")
        for i in range(1, 4):
            started = time.monotonic()
            ok, detail = await validate_provider_call(keyed, "m")
            elapsed = time.monotonic() - started
            print(f"pass {i}: ok={ok} elapsed={elapsed:.2f}s detail={detail[:90]!r}")

    asyncio.run(run())
    server.shutdown()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())