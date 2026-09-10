"""AUDIT-3 scratch probe 2 — banner_dismiss post-click navigation (Rule 13).

Question: can dismiss_banners click a non-banner element (generic fallback
selector) whose click handler navigates the main frame — and would the
subsequent capture (page.content()) silently store the WRONG page?

Real Chromium, local file:// pages, the production dismiss_banners
function unmodified.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "backend")

from playwright.async_api import async_playwright  # noqa: E402

from worker.banner_dismiss import dismiss_banners  # noqa: E402

HERE = Path(__file__).parent


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto((HERE / "site_index.html").as_uri())
        print(f"before dismiss: url={page.url}")
        evidence = await dismiss_banners(page, timeout_ms=3000)
        print(f"dismiss evidence: {evidence}")
        # Mirror what fetcher does next: a short settle, then scroll pass,
        # stability wait, then page.content().
        await page.wait_for_timeout(1000)
        html = await page.content()
        print(f"after dismiss:  url={page.url}")
        print(f"captured DOM contains WRONG-PAGE marker: {'WRONG CONTENT' in html}")
        print(f"captured DOM contains real-page marker: {'Real content' in html}")
        await browser.close()


asyncio.run(main())
