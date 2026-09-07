"""Child-process capture helper for tests/test_capture_e2e.py (Phase 13).

Runs one `worker.fetcher.fetch_page` capture in a subprocess and writes the
result as JSON to the path in CAPTURE_CHILD_OUT. The parent test kills this
process if a capture wedges the Playwright transport (observed live on
tagesschau.de during the Phase-13 gate: a CDP page.evaluate that never
returns hangs the capture coroutine outside every internal time bound).

The parent never calls asyncio.wait_for around fetch_page in-process:
cancelling a Playwright async transition corrupts the transport (the first
gate run's netflix.com deadlock). Process isolation is the only clean
escape.

Importable path: the script's directory is backend/tests; backend/ carries
the `worker` package, so it is inserted into sys.path explicitly (the
invocation cwd is backend/, but sys.path[0] is the script's own directory).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _write_payload(out: str, payload: dict) -> None:
    """Sync helper (offloaded via to_thread): serialize the capture result
    to the output JSON file. Runs after the fetch is done, so the event
    loop is idle when the blocking write happens."""
    with open(out, "w", encoding="utf-8", errors="replace") as fh:
        json.dump(payload, fh, ensure_ascii=False)


async def _main() -> None:
    url = sys.argv[1]
    out = os.environ["CAPTURE_CHILD_OUT"]
    try:
        from worker.fetcher import fetch_page

        result = await fetch_page(url)
        payload = {
            "ok": True,
            "html": result.html,
            "screenshot": list(result.screenshot),
            "final_url": result.final_url,
            "http_status": result.http_status,
            "headers": result.headers,
            "capture_evidence": result.capture_evidence,
        }
    except Exception as exc:  # noqa: BLE001 — serialize any failure honestly
        payload = {"ok": False, "error": str(exc)[:500]}
    await asyncio.to_thread(_write_payload, out, payload)


if __name__ == "__main__":
    asyncio.run(_main())