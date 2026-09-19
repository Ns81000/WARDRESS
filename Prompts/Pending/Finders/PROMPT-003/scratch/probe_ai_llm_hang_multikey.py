"""PROMPT-003 Phase 4E scratch probe #2 (preserved for reproducibility, per the
effort's scratch-probe precedent — Rule 5/10: it is not a pytest and not part
of any suite).

Rule 13 correction probe: the first probe showed a single-deployment hung call
costs exactly ONE 30 s timeout (the Router cools the only deployment after its
first failure, so `num_retries` does not multiply network waits). This probe
measures whether MULTI-KEY providers (one litellm deployment per key) amplify
the stall, three passes (Rule 18).

Run:
  backend\\.venv\\Scripts\\python.exe Prompts\\Pending\\Finders\\PROMPT-003\\scratch\\probe_ai_llm_hang_multikey.py
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
os.environ.setdefault(
    "CREDENTIALS_ENCRYPTION_KEY", "probe-encryption-key-not-for-production-0123456789"
)

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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"hanging provider at {base_url}; timeout={_REQUEST_TIMEOUT}s retries={_NUM_RETRIES}")

    two_keys = AiProvider(
        label="probe-hang-2keys",
        provider_type="openai_compatible",
        base_url=base_url,
        credentials_encrypted=encrypt_keys(["sk-probe-key-one-0123456789", "sk-probe-key-two-0123456789"]),
    )

    async def run() -> None:
        for i in range(1, 4):
            started = time.monotonic()
            ok, detail = await validate_provider_call(two_keys, "m")
            elapsed = time.monotonic() - started
            print(f"2-key pass {i}: ok={ok} elapsed={elapsed:.2f}s detail={detail[:70]!r}")

    asyncio.run(run())
    server.shutdown()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())