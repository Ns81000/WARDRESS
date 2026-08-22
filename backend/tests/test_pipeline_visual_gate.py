"""Pipeline gating regression tests: the visual layer must never be
gated off by an identical content hash.

The hashed content is the serialized DOM (`page.content()`), which says
nothing about externally-referenced assets or pixels. A defacement that
swaps server-side assets (/banner.png, /logo.png, external JS painting
over the page, cross-origin iframe bodies) leaves the DOM serialization
byte-identical while changing what visitors see. Layer 4 holds the only
ground truth for that class, so it must run even when layer 1 scores
0.0 — audit finding: "Layer-1 hash gate permanently disables the visual
layer for defacements that don't alter the serialized DOM".
"""

import io

from PIL import Image, ImageDraw

from worker.detection.pipeline import GATED_BY_IDENTICAL_HASH, run_detection
from worker.detection.types import PageData, ScanPageData
from worker.hashing import content_sha256

HTML = "<html><body><h1>Acme</h1><p>Reliable widgets.</p></body></html>"
W, H = 683, 400


def _png(swaps=(), text=None) -> bytes:
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 40, W, H], fill=(235, 235, 235))  # shared footer
    d.rectangle([0, 0, W, 24], fill=(245, 245, 245))  # shared top bar
    for box, rgb in swaps:
        d.rectangle(box, fill=rgb)
    if text:
        d.text((20, 45), text, fill=(250, 250, 250))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pages(baseline_png: bytes, current_png: bytes):
    base = PageData(
        html=HTML,
        screenshot=baseline_png,
        final_url="https://acme.com/",
        content_hash=content_sha256(HTML),
    )
    cur = ScanPageData(
        html=HTML,
        screenshot=current_png,
        final_url="https://acme.com/",
        content_hash=content_sha256(HTML),
    )
    assert base.content_hash == cur.content_hash
    return base, cur


BANNER_BOX = ((0, 24, W, 144),)


def test_visual_layer_not_in_identical_hash_gate() -> None:
    """The identical-hash gate exists for DOM-derived layers only; layer 4
    compares pixels, which an identical DOM serialization cannot vouch for."""
    assert "layer4_visual_diff" not in GATED_BY_IDENTICAL_HASH


def test_banner_asset_swap_with_identical_dom_runs_visual_layer() -> None:
    base, cur = _pages(
        _png(swaps=[(*BANNER_BOX, (200, 210, 220))]),
        _png(swaps=[(*BANNER_BOX, (10, 10, 10))], text="HACKED BY CYBER WARRIORS"),
    )
    results = run_detection(base, cur)
    l4 = results["layer4_visual_diff"]
    assert not l4.get("skipped")
    assert l4["score"] > 0.2
    assert l4["evidence"]["ssim"] < 0.9
    assert l4["evidence"]["phash_distance_bits"] > 32


def test_logo_asset_swap_with_identical_dom_runs_visual_layer() -> None:
    # A small server-side asset swap must also open the visual track —
    # guards against re-gating that only catches full-banner takeovers.
    base, cur = _pages(
        _png(swaps=[((0, 24, 120, 72), (200, 210, 220))]),
        _png(swaps=[((0, 24, 120, 72), (160, 30, 30))]),
    )
    results = run_detection(base, cur)
    l4 = results["layer4_visual_diff"]
    assert not l4.get("skipped")
    assert l4["score"] > 0.01


def test_pixel_change_raises_fused_risk_above_identical_control() -> None:
    clean = _png()
    control = run_detection(*_pages(clean, clean))
    defaced = _png(swaps=[(*BANNER_BOX, (10, 10, 10))], text="HACKED BY CYBER WARRIORS")
    attack = run_detection(*_pages(clean, defaced))
    assert not control["layer4_visual_diff"].get("skipped")
    assert control["layer4_visual_diff"]["score"] == 0.0
    assert not attack["layer4_visual_diff"].get("skipped")
    assert attack["layer9_fusion"]["score"] > control["layer9_fusion"]["score"], (
        "visual evidence must raise fused risk relative to the pixel-identical scan"
    )


def test_missing_screenshots_under_identical_hash_still_report_layer4() -> None:
    # Artifact loss must surface as a ran-with-note layer result, never as
    # a silent gate skip: the degradation stays visible downstream.
    base, cur = _pages(b"", b"")
    results = run_detection(base, cur)
    l4 = results["layer4_visual_diff"]
    assert not l4.get("skipped")
    assert l4["score"] == 0.0
    assert "note" in l4["evidence"]
