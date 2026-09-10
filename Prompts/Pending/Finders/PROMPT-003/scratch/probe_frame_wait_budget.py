"""AUDIT-3 scratch probes 3/3b — consent-iframe banner handling (Rule 13).

3.  page.wait_for_selector(combined) does NOT pierce iframes (page-level
    selector waits cover the main frame only).
3b. dismiss_banners snapshots `_frames(page)` ONCE before the late-banner
    wait, so a consent iframe that attaches late is invisible to the final
    pass — the banner is never clicked. Sanity control: a visible-from-load
    iframe IS clicked (Phase 5's tested shape).
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, "backend")

from playwright.async_api import async_playwright  # noqa: E402

from worker.banner_dismiss import DISMISS_SELECTORS, dismiss_banners  # noqa: E402

HERE = Path(__file__).parent

PARENT_LATE = """<!doctype html>
<html><head><title>Parent</title></head>
<body>
  <h1>Parent content</h1>
  <iframe id="consent" src="frame_child.html"></iframe>
  <script>
    document.getElementById('consent').style.display = 'none';
    setTimeout(() => {
      document.getElementById('consent').style.display = 'block';
    }, 2500);
  </script>
</body></html>"""

PARENT_VISIBLE = """<!doctype html>
<html><head><title>Parent visible</title></head>
<body>
  <h1>Parent content</h1>
  <iframe id="consent" src="frame_child.html"></iframe>
</body></html>"""

CHILD = """<!doctype html>
<html><body>
  <button class="cookie-accept" onclick="parent.document.title='CLICKED'">Accept all</button>
</body></html>"""


async def main() -> None:
    child_path = HERE / "frame_child.html"
    child_path.write_text(CHILD, encoding="utf-8")
    late_path = HERE / "probe3_parent.html"
    late_path.write_text(PARENT_LATE, encoding="utf-8")
    visible_path = HERE / "probe3_parent_visible.html"
    visible_path.write_text(PARENT_VISIBLE, encoding="utf-8")

    combined = ",".join(DISMISS_SELECTORS)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        page = await browser.new_page()
        await page.goto(late_path.as_uri())
        start = time.monotonic()
        try:
            await page.wait_for_selector(combined, state="visible", timeout=3000)
            print(f"[3] page.wait_for_selector found it in {(time.monotonic()-start)*1000:.0f} ms")
        except Exception:
            print(
                f"[3] page.wait_for_selector TIMED OUT ({(time.monotonic()-start)*1000:.0f} ms) "
                "— iframe banner invisible to the page-level wait"
            )

        p1 = await browser.new_page()
        await p1.goto(visible_path.as_uri())
        await asyncio.sleep(0.5)
        print(f"[3b-control] frames at first pass = {len(p1.frames)}")
        ev = await dismiss_banners(p1, timeout_ms=3000)
        print(f"[3b-control] evidence={ev} title={await p1.title()!r}")

        p2 = await browser.new_page()
        await p2.goto(late_path.as_uri())
        start = time.monotonic()
        evidence = await dismiss_banners(p2, timeout_ms=3000)
        elapsed = (time.monotonic() - start) * 1000
        frames_after = len(p2.frames)
        title = await p2.title()
        print(
            f"[3b] evidence={evidence} elapsed={elapsed:.0f} ms "
            f"frames_after={frames_after} title={title!r}"
        )
        clicked = "CLICKED" in title
        print(f"[3b] late iframe banner clicked: {clicked}; full budget burned: {elapsed > 2400}")
        await browser.close()


asyncio.run(main())
