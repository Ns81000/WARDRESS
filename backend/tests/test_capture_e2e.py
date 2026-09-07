"""End-to-end capture validation gate (PROMPT-002 Phase 13).

LIVE-NETWORK suite. Every test is marked `@pytest.mark.network` and is skipped
by the hermetic default in backend/pyproject.toml (`addopts = "-m 'not network'"`
plus the registered `network` marker) — the deselect is STRUCTURAL config, not
an agent remembering to opt out. Run the gate manually as a validation step:

    cd backend && uv run --frozen pytest -m network -q -s tests/test_capture_e2e.py

The gate validates the Phases 1-7 capture stack (stealth, Cloudflare challenge
detection, scrolling/lazy capture, screenshot cap, consent-banner dismissal,
transient retry, capture_evidence) against `test_sites_comprehensive.txt`, a
real-world list extending the 88-URL `wardress-test-sites (1).txt` seed:

- Per-category capture-rate validation with the spec's honesty rules: a
  Cloudflare-protected site that is correctly DETECTED and reported as a block
  (FetchError BOT_PROTECTION) counts as a PASS — the contract is to recognize a
  block, not defeat every WAF. Clean captures and correctly detected challenges
  are recorded as SEPARATE numbers.
- Capture-time statistics on 5 representative sites (median, P95).
- Capture CONSISTENCY: the same site captured twice ~1 minute apart must be
  structurally similar — different in detail (dynamic content exists) but the
  same DOM skeleton. This is the direct measure of the whole effort's
  capture-consistency improvements.

Reporting: per-site records are printed and, when CAPTURE_E2E_REPORT points at
a file, appended as JSONL for the Phase-13 reporting table. That path is a
scratch file OUTSIDE the repo (rule: never commit scratch work).

This phase touches capture validation only: no detection layer, no SSRF policy,
no runtime configuration changes.
"""

import asyncio
import json
import logging
import os
import re
import statistics
import struct
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import pytest

from worker.fetcher import (
    BOT_PROTECTION_ERROR,
    FetchError,
    FetchResult,
)
from worker.stealth import MAX_SCREENSHOT_HEIGHT

logger = logging.getLogger(__name__)

# --- Site list --------------------------------------------------------------

SITES_FILE = Path(__file__).resolve().parent / "test_sites_comprehensive.txt"

# Reporting-table categories (order matters: it is the table's row order).
CATEGORY_ORDER = [
    "SPA/JS Heavy",
    "Cloudflare",
    "Lazy Loading",
    "Cookie Banner",
    "Non-Latin",
    "Gov/Security",
    "Static Control",
    "E-commerce",
]

# Phase-13 spec minimums — collection fails loudly if the committed list
# regresses below them (no network needed to enforce this shape).
MINIMUM_SITES = {
    "SPA/JS Heavy": 10,
    "Cloudflare": 5,
    "Lazy Loading": 10,
    "Cookie Banner": 10,
    "Non-Latin": 5,
    "Gov/Security": 5,
    "Static Control": 5,
    "E-commerce": 5,
}

_SECTION_RE = re.compile(
    r"^#\s*(" + r"|".join(re.escape(c) for c in CATEGORY_ORDER) + r")\s*$"
)

# --- Validation targets ------------------------------------------------------

CONTEXT_VIEWPORT_WIDTH = 1366  # worker.stealth.CONTEXT_VIEWPORT width

CONSISTENCY_INTERVAL_S = 60  # the spec's "1 minute apart"
# Structural-similarity floor for two captures of the same page, measured
# not guessed (Phase-13 gate run 2026-09-07): two live theguardian.com
# captures 1 minute apart scored 0.7949 on this order-sensitive tag-sequence
# metric — the guardian's inline ad/live-churn slots legitimately reorder
# ~21% of the ordered tag stream between visits while the DOM skeleton
# (head/header/nav/article layout/footer) is preserved. A broken capture
# (wrong site, no JS render, blank page) scores far below 0.70. 0.70 is the
# same-page-family separator; the length-ratio guard below catches outright
# size collapse.
CONSISTENCY_SKELETON_MIN = 0.70
# Length-ratio floor (min/max) — a 10x page-size collapse is not "similar".
CONSISTENCY_LENGTH_MIN = 0.60

PERF_SITES = [  # (label, url) — 1 of each representative type
    ("static", "https://example.com/"),
    ("spa", "https://vuejs.org/"),
    ("lazy", "https://unsplash.com/"),
    ("cloudflare", "https://www.cloudflare.com/"),
    ("cookie-banner", "https://www.bbc.co.uk/news"),
]
PERF_MEDIAN_MAX_S = 30.0
PERF_P95_MAX_S = 60.0


def load_sites() -> dict[str, list[str]]:
    """Parse the sectioned site list, in file order.

    Raises ValueError on a malformed file (unknown section header, URL lines
    with no preceding section) — the hermetic suite collects this file, so a
    format regression fails collection without touching the network.
    """
    sites: dict[str, list[str]] = {c: [] for c in CATEGORY_ORDER}
    current: str | None = None
    for raw in SITES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        section = _SECTION_RE.match(line)
        if section:
            current = section.group(1)
            continue
        if line.startswith("#"):
            continue  # prose comment
        if current is None:
            raise ValueError(
                f"{SITES_FILE.name}: URL line before any section header: {line}"
            )
        parsed = urlparse(line)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                f"{SITES_FILE.name}: not an absolute http(s) URL: {line}"
            )
        sites[current].append(line)
    return sites


SITE_CATEGORIES = load_sites()

# Report record accumulator (JSONL, append-only). CAPTURE_E2E_REPORT is a
# scratch path the operator sets when running the gate; never defaulted into
# the repo tree.
_REPORT_PATH = os.environ.get("CAPTURE_E2E_REPORT")


def _write_report(record: dict) -> None:
    if _REPORT_PATH is None:
        return
    with open(_REPORT_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


# --- Pure helpers (no network) ----------------------------------------------


def _png_dims(png: bytes) -> tuple[int, int] | None:
    """(width, height) from the PNG IHDR, or None when not a valid PNG."""
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) < 24:
        return None
    return struct.unpack(">II", png[16:24])


def _html_ok(html: str) -> tuple[bool, str]:
    """'Expected structural elements': non-empty rendering with a document
    skeleton and measurable visible text or markup depth. The bar is
    deliberately modest so a JS-heavy page that renders a thin-but-real DOM
    still passes; a blank/error shell does not."""
    if not html:
        return False, "empty-html"
    if len(html) < 300:
        return False, f"html-len-{len(html)}"
    lower = html.lower()
    if "<html" not in lower and "<body" not in lower:
        return False, "no-document-skeleton"
    visible = re.sub(r"<[^>]+>", " ", html)
    if len(visible.strip()) < 80:
        tag_count = len(re.findall(r"<[a-z][a-z0-9-]*\b", lower))
        if tag_count < 60:
            return False, "thin-dom"
    return True, "ok"


def _screenshot_ok(evidence: dict, dims: tuple[int, int] | None) -> tuple[bool, str]:
    """Reasonable PNG dimensions: ~1366 wide (the capture viewport) and tall
    enough to represent the measured page. An uncapped page's full-page raster
    must reach the probed document height (catching Playwright's clamp-to-
    viewport failure mode); a capped page must be exactly the cap."""
    if dims is None:
        return False, "invalid-png"
    width, height = dims
    # "~1366": site-driven layouts can shift the CSS pixel width a percent
    # (e.g. spotify.com rasterizes 1378px). ±20 (~1.5%) is reasonable-
    # dimensions territory; a mobile/zoomed misrender would be far wider.
    if not (CONTEXT_VIEWPORT_WIDTH - 20 <= width <= CONTEXT_VIEWPORT_WIDTH + 20):
        return False, f"width-{width}"
    actual_height = int(evidence.get("actual_height") or 0)
    if evidence.get("screenshot_capped"):
        if height == MAX_SCREENSHOT_HEIGHT:
            return True, "ok"
        return False, f"capped-height-{height}"
    if actual_height <= 0:  # height probe degraded: no cap decision recorded
        return height >= 600, f"height-{height}"
    return height >= max(0, actual_height - 60), (
        f"height-{height}-vs-{actual_height}"
    )


def _structural_skeleton(html: str) -> list[str]:
    """Tag skeleton: the ordered sequence of element names in the document.
    Text, attributes and dynamic values are stripped, so timestamps, ad IDs
    and nonces cannot dominate the comparison."""
    return [t.lower() for t in re.findall(r"<([a-z][a-z0-9-]*)\b", html)]


def _structural_similarity(html_a: str, html_b: str) -> float:
    """SequenceMatcher ratio over the two tag skeletons. 1.0 = identical
    structure; dynamic reorders/insertions lower it modestly."""
    skel_a = _structural_skeleton(html_a)
    skel_b = _structural_skeleton(html_b)
    if not skel_a or not skel_b:
        return 0.0
    return SequenceMatcher(None, skel_a, skel_b).ratio()


def _length_ratio(html_a: str, html_b: str) -> float:
    """min/max of the two raw HTML lengths — a structural-collapse guard."""
    len_a, len_b = len(html_a), len(html_b)
    if max(len_a, len_b) == 0:
        return 0.0
    return min(len_a, len_b) / max(len_a, len_b)


# --- Live capture plumbing --------------------------------------------------
#
# Per-site captures run in a CHILD PROCESS so a wedged Playwright transition
# (a CDP page.evaluate that never returns — observed live on tagesschau.de
# during this phase's gate run: the Python loop stays alive but the capture
# coroutine hangs outside every internal time bound) can be killed at the OS
# level without taking down the whole gate. The child (backend/tests/
# _capture_child_impl.py) writes a JSON record to a temp file; the parent
# enforces a wall-clock budget and `kill()`s the child on expiration. This is
# deliberately NOT `asyncio.wait_for` around fetch_page in-process: mid-cancell
# corrupts the Playwright async transport, which hangs the whole event loop
# (the first gate run's netflix.com deadlock). See the Phase-13 log entry.

_CAPTURE_CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_capture_child_impl.py")
_SCRATCH_DIR = os.environ.get("TEMP", os.path.dirname(_CAPTURE_CHILD))
# Wall-clock per-site budget. A working capture finishes in <60s (observed
# range this phase: 11-49s); `fetch_page`'s absolute worst case (BOTH internal
# attempts at max: goto/challenge/wait/settle/banner/scroll/stability/
# screenshot) is ~270s but no non-wedged site approaches it. 180s is generous
# for anything genuinely working and catches a wedged transition (which does
# NOT return, so it would otherwise hang forever) at ~3 minutes.
_SITE_BUDGET_S = 180


async def _capture_one(url: str) -> tuple[FetchResult | None, str | None, float]:
    """One `fetch_page` call, isolated in a child process under _SITE_BUDGET_S.

    Returns (result, None) on success; (None, error-string) on any failure,
    including a killed (wedged) child reported as 'stalled ...'. The parent
    loop never holds a Playwright connection, so a wedged child is disposed of
    cleanly."""

    out = os.path.join(_SCRATCH_DIR, "phase13-child", f"{abs(hash(url)):x}.json")
    env = dict(os.environ)
    env.pop("CAPTURE_E2E_REPORT", None)
    env["CAPTURE_CHILD_OUT"] = out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, _CAPTURE_CHILD, url, env=env,
            cwd=os.path.dirname(_CAPTURE_CHILD),  # backend/
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=_SITE_BUDGET_S)
        except TimeoutError:
            # Kill the whole process tree — the child's Playwright launches
            # chromium headless-shell descendants that proc.kill() alone
            # would orphan on Windows (they'd keep polling an dead transport).
            await asyncio.to_thread(_kill_tree, proc.pid)
            return None, "stalled (capture exceeded the site budget)", time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 — record anything unexpected honestly
        logger.warning("Child launcher failed for %s", url, exc_info=True)
        return None, f"unexpected:{exc.__class__.__name__}", time.monotonic() - started

    payload = await asyncio.to_thread(_read_output_file, out)
    if payload is None:
        # Child exited without writing its output file.
        return None, "child-crashed", time.monotonic() - started
    decoded = _decode_child(payload)
    if isinstance(decoded, FetchError):
        return None, str(decoded), time.monotonic() - started
    return decoded, None, time.monotonic() - started


def _read_output_file(out: str):
    """Sync helper (offloaded via to_thread): read the child's JSON output
    and delete it, or None when the child never wrote it."""
    if not os.path.exists(out):
        return None
    try:
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:  # noqa: BLE001 — unreadable output is an honest failure
        return None
    if os.environ.get("CAPTURE_E2E_KEEP_CHILD") is None:
        try:
            os.remove(out)
        except OSError:
            pass
    return payload


def _kill_tree(pid: int) -> None:
    """Force-kill a process and its whole descendant tree (Windows-only tree
    semantics = taskkill /T). Best-effort: a gone process is fine."""
    taskkill = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "taskkill.exe"
    )
    try:
        subprocess.run(
            [taskkill, "/F", "/T", "/PID", str(pid)],
            capture_output=True, check=False, timeout=15,
        )
    except Exception:  # noqa: BLE001 — process may already be gone
        logger.debug("taskkill on pid %s failed", pid, exc_info=True)


def _decode_child(payload: dict):
    """Rebuild a FetchResult — or surface the failed capture's error as a
    FetchError (so `_classify` sees the exact BOT_PROTECTION_ERROR contract for
    a correctly detected Cloudflare block) — from the child's JSON."""
    if payload.get("ok"):
        return FetchResult(
            html=payload["html"],
            screenshot=bytes(payload["screenshot"]),
            final_url=payload["final_url"],
            http_status=payload["http_status"],
            headers=payload["headers"],
            capture_evidence=payload["capture_evidence"],
        )
    if payload.get("error") == BOT_PROTECTION_ERROR:
        return FetchError(BOT_PROTECTION_ERROR)
    if payload.get("error"):
        return FetchError(payload["error"])
    return FetchError("child capture failed with an unknown error")


def _classify(
    category: str,
    url: str,
    result: FetchResult | None,
    error: str | None,
    elapsed_s: float,
) -> dict:
    """Per-site pass/fail classification with the spec's honesty rules.

    Cloudflare: PASS = clean real-content capture OR correctly detected
    challenge block (two SEPARATE numbers — clean / detected). Every other
    category: PASS = a clean capture (HTTP 200, valid PNG with reasonable
    dimensions, expected HTML structure). Captures that succeeded but carry
    quality warts (scroll-capped, screenshot-capped, banner not clicked,
    transient retries) still count as captured — the warts become Notes.
    """
    base = {
        "category": category,
        "url": url,
        "elapsed_s": round(elapsed_s, 2),
        "clean": False,
        "detected": False,
        "pass": False,
        "note": "",
        # Full report key set with None defaults: aggregation reads these
        # directly, so EVERY record (including error records) must carry
        # them. A missing key here would KeyError the category summary
        # (observed live in the first gate run of this phase).
        "status": None,
        "quality": None,
        "scroll_capped": None,
        "screenshot_capped": None,
        "retry_count": None,
        "banner_dismissed": None,
    }
    if error is not None:
        base["status"] = "error"
        if category == "Cloudflare" and error == BOT_PROTECTION_ERROR:
            base["detected"] = True
            base["pass"] = True
            base["note"] = "bot-block-detected"
        else:
            base["note"] = f"fetch-error: {error[:160]}"
        return base

    ev = result.capture_evidence or {}
    base["status"] = result.http_status
    base["quality"] = ev.get("capture_quality")
    base["scroll_capped"] = bool(ev.get("capped"))
    base["screenshot_capped"] = bool(ev.get("screenshot_capped"))
    base["retry_count"] = ev.get("retry_count")
    if category == "Cookie Banner":
        base["banner_dismissed"] = bool(ev.get("dismissed"))

    status_ok = result.http_status == 200
    png_ok, png_reason = _screenshot_ok(ev, _png_dims(result.screenshot))
    html_ok, html_reason = _html_ok(result.html)
    clean = status_ok and png_ok and html_ok

    reasons: list[str] = []
    if not status_ok:
        reasons.append(f"http-{result.http_status}")
    if not png_ok:
        reasons.append(f"png:{png_reason}")
    if not html_ok:
        reasons.append(f"html:{html_reason}")
    # Quality warts are notes, not failures — a successful-but-imperfect
    # capture is still a successful capture (Phase-4 taxonomy: partial).
    if ev.get("capped"):
        reasons.append("scroll-capped")
    if ev.get("screenshot_capped"):
        reasons.append("screenshot-capped")
    if ev.get("stable") is False:
        reasons.append("content-unstable")
    if ev.get("retry_count"):
        reasons.append(f"retried-{ev['retry_count']}")

    base["clean"] = clean
    base["pass"] = clean
    base["note"] = "; ".join(reasons) if reasons else "ok"
    return base


# --- Tests ------------------------------------------------------------------


@pytest.mark.network
@pytest.mark.parametrize("category", CATEGORY_ORDER)
async def test_network_category_capture_gate(category: str) -> None:
    """Capture every site in one category and enforce the Phase-13 bar:
    >=90% clean captures on non-Cloudflare categories; >=90% clean-OR-
    correctly-detected on Cloudflare (the two numbers reported separately)."""
    sites = SITE_CATEGORIES[category]
    assert len(sites) >= MINIMUM_SITES[category], (
        f"{category} has {len(sites)} sites, below the "
        f"{MINIMUM_SITES[category]} minimum"
    )

    records = []
    for url in sites:
        result, error, elapsed_s = await _capture_one(url)
        rec = _classify(category, url, result, error, elapsed_s)
        records.append(rec)
        _write_report(rec)
        logger.info(
            "capture %-12s %-40s pass=%s %.1fs%s",
            category, url, rec["pass"], elapsed_s,
            f"  [{rec['note']}]" if rec["note"] else "",
        )

    n_sites = len(records)
    clean = sum(1 for r in records if r["clean"])
    detected = sum(1 for r in records if r["detected"])
    passed = sum(1 for r in records if r["pass"])
    avg = statistics.mean(r["elapsed_s"] for r in records)
    scroll_capped = sum(1 for r in records if r["scroll_capped"])
    screenshot_capped = sum(1 for r in records if r["screenshot_capped"])
    banners = sum(1 for r in records if r["banner_dismissed"] is True)

    summary = {
        "category": category, "sites": n_sites, "clean": clean,
        "detected": detected, "passed": passed, "avg_s": round(avg, 2),
        "scroll_capped": scroll_capped, "screenshot_capped": screenshot_capped,
        "banner_dismissed": banners,
    }
    _write_report({"kind": "category-summary", **summary})
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if category == "Cloudflare":
        assert passed >= 0.9 * n_sites, (
            f"{category}: {passed}/{n_sites} pass (clean={clean}, "
            f"detected={detected}) is below the 90% clean-or-detected bar"
        )
    else:
        assert clean >= 0.9 * n_sites, (
            f"{category}: {clean}/{n_sites} clean captures is below the "
            f"90% clean-capture bar"
        )


@pytest.mark.network
async def test_network_performance_regression() -> None:
    """Time 5 representative captures (static/SPA/lazy/Cloudflare/cookie-
    banner). Median < 30s, P95 < 60s. Recorded against the prior smoke
    number (Phase 6 measured example.com at ~10.2s inside the worker
    container)."""
    times: list[float] = []
    for label, url in PERF_SITES:
        result, error, elapsed_s = await _capture_one(url)
        rec = {
            "kind": "perf", "label": label, "url": url,
            "elapsed_s": round(elapsed_s, 2),
            "status": (
                "ok"
                if result is not None and result.http_status == 200
                else ("error" if error is not None else f"http-{result.http_status}")
            ),
        }
        if error is not None:
            rec["note"] = error[:120]
        _write_report(rec)
        print(f"perf {label:12} {rec['status']:5} {elapsed_s:7.2f}s  {url}")
        times.append(elapsed_s)

    ordered = sorted(times)
    median = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    summary = {
        "kind": "perf-summary",
        "median_s": round(median, 2),
        "p95_s": round(p95, 2),
        "min_s": round(ordered[0], 2),
        "max_s": round(ordered[-1], 2),
    }
    _write_report(summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    assert median < PERF_MEDIAN_MAX_S, (
        f"capture-time median {median:.1f}s exceeds the {PERF_MEDIAN_MAX_S}s bar"
    )
    assert p95 < PERF_P95_MAX_S, (
        f"capture-time P95 {p95:.1f}s exceeds the {PERF_P95_MAX_S}s bar"
    )


@pytest.mark.network
async def test_network_capture_consistency() -> None:
    """Capture the SAME site twice ~1 minute apart and assert structural
    similarity — different in detail (dynamic content exists), same DOM
    skeleton. This is the direct measure of the capture-consistency
    improvements from stealth + scrolling + banner suppression: two captures
    of a live news page must agree on shape even while headlines/ads churn.
    """
    url = "https://www.theguardian.com/"
    first, first_err, first_s = await _capture_one(url)
    assert first is not None and first_err is None, (
        f"first capture failed: {first_err or 'timeout'}"
    )
    # The spec's "1 minute apart", chunked to honor the session-ops rule that
    # long waits are never one giant uninterruptible sleep.
    for _ in range(3):
        await asyncio.sleep(CONSISTENCY_INTERVAL_S // 3)

    second, second_err, second_s = await _capture_one(url)
    assert second is not None and second_err is None, (
        f"second capture failed: {second_err or 'timeout'}"
    )

    first_ev = first.capture_evidence or {}
    second_ev = second.capture_evidence or {}
    skeleton = _structural_similarity(first.html, second.html)
    length_ratio = _length_ratio(first.html, second.html)
    print(
        f"consistency skeleton={skeleton:.4f} length_ratio={length_ratio:.3f} "
        f"heights={first_ev.get('actual_height')}/{second_ev.get('actual_height')} "
        f"times={first_s:.1f}s/{second_s:.1f}s"
    )
    _write_report({
        "kind": "consistency", "url": url,
        "skeleton_similarity": round(skeleton, 4),
        "length_ratio": round(length_ratio, 3),
        "first_s": round(first_s, 2), "second_s": round(second_s, 2),
    })

    assert skeleton >= CONSISTENCY_SKELETON_MIN, (
        f"structural similarity {skeleton:.3f} < {CONSISTENCY_SKELETON_MIN} — "
        f"the two captures disagree on DOM shape"
    )
    assert length_ratio >= CONSISTENCY_LENGTH_MIN, (
        f"page-size ratio {length_ratio:.2f} < {CONSISTENCY_LENGTH_MIN} — the "
        f"captures differ too much in size to be the same page state"
    )
    assert first.http_status == 200 and second.http_status == 200