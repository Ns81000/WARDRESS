"""Layer 4 — visual diff: SSIM + perceptual hashes + chroma shift (§5).

Full-page screenshots are compared four ways:
- SSIM (scikit-image structural_similarity) on downscaled grayscale —
  data_range passed explicitly per the skimage docs' floating-point
  warning (docs-cache/skimage-metrics.html).
- pHash + dHash (imagehash) — robust to compression/minor rendering
  noise; hamming distance normalized by hash bits.
- a cheap RGB chroma-shift term (per-channel mean/standard-deviation
  deltas over the compared region, behind a render-noise deadband) so a
  hue-only defacement — recolored banners and overlays that preserve
  luminance almost exactly — can no longer read as "pixels identical".

Full-page captures of the same site can legitimately differ in height
(a new blog post pushes the footer down), so SSIM compares the shared
top region at a common width/height; the raw dimensions go into
evidence, and the perceptual hashes (whole-image) still see the tails.
The chroma term covers the same shared region.

An unreadable/absent screenshot on either side is a capture problem,
not a measurement: the layer reports a degraded result (score None,
`degraded=True`) so fusion treats the visual channel as UNKNOWN instead
of silently reading it as "pixels identical" — that conflation once let
a broken capture pipeline disable the product's only pixel ground truth
while scans completed looking clean.

Operating point: a pure hue-only recolor lands around 0.15-0.20 — an
honest "the pixels changed" reading that flips the verdict to changed,
while staying below what the fused model would flag on this channel
alone. That is deliberate: legitimate brand refreshes are pixel-wise
indistinguishable in kind from hostile recolors, so corroboration from
the content layers (or the rule floors) is what separates them.
"""

import io

import imagehash
import numpy as np
from PIL import Image, UnidentifiedImageError
from skimage.metrics import structural_similarity

from worker.detection.types import PageData, degraded_result, layer_result

# Compare at a bounded size: SSIM on multi-megapixel full-page PNGs is
# slow and no more informative for "did the page visibly change".
COMPARE_WIDTH = 683  # half of the 1366px capture viewport
MAX_COMPARE_HEIGHT = 4096
HASH_SIZE = 16  # 16x16 -> 256-bit pHash/dHash: finer than the default 8

# Chroma-shift deadband (0..255 per-channel units): repeated renders of
# identical content differ by ~1 unit of anti-aliasing/encoder noise;
# anything under this is silence, not signal.
_CHROMA_DEADBAND_255 = 2.0
# A maximal chroma-only change contributes at most this much to the score
# on its own — visible, never single-handedly flag-worthy.
_W_CHROMA = 0.30

# Pillow refuses decompression-bomb images by default (Image.MAX_IMAGE_PIXELS);
# our own screenshots are trusted, so lift the ceiling a little rather than
# disabling the guard entirely.
Image.MAX_IMAGE_PIXELS = 512 * 1024 * 1024 // 4


def _load_rgb(png: bytes) -> Image.Image | None:
    if not png:
        return None
    try:
        img = Image.open(io.BytesIO(png))
        img.load()
        return img.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


def _common_size(a: Image.Image, b: Image.Image) -> tuple[int, int]:
    # Scale both to the compare width, then crop/pad to the shorter height
    # (bounded) so SSIM windows align.
    def scaled_h(img: Image.Image) -> int:
        return max(8, round(img.height * (COMPARE_WIDTH / img.width)))

    h = min(scaled_h(a), scaled_h(b), MAX_COMPARE_HEIGHT)
    return COMPARE_WIDTH, h


def _mask_regions(
    img: Image.Image,
    bboxes: list[tuple[float, float, float, float]],
    reference: Image.Image,
) -> Image.Image:
    """Fill suppressed regions with a uniform mid-gray on a copy. The
    fractions are resolved against the REFERENCE (baseline) geometry —
    the capture the user drew on — then scaled to this image through the
    width ratio only. Widths match across captures of the same viewport;
    heights vary with content, and scaling y by each image's own height
    would drift the mask off the intended content on a taller page."""
    if not bboxes:
        return img
    scale = img.width / reference.width if reference.width else 1.0
    out = img.copy()
    for x, y, w, h in bboxes:
        left = round(x * reference.width * scale)
        top = round(y * reference.height * scale)
        right = min(img.width, round((x + w) * reference.width * scale))
        bottom = min(img.height, round((y + h) * reference.height * scale))
        if right > left and bottom > top:
            out.paste(128, (left, top, right, bottom))
    return out


def layer4_visual_diff(
    baseline: PageData,
    current: PageData,
    suppress_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> dict:
    b_img = _load_rgb(baseline.screenshot)
    c_img = _load_rgb(current.screenshot)

    if b_img is None or c_img is None:
        return degraded_result(
            "screenshot missing or unreadable on one side — visual diff not computed",
            baseline_screenshot_ok=b_img is not None,
            current_screenshot_ok=c_img is not None,
        )

    # Suppressed regions are masked identically on both sides BEFORE any
    # comparison — SSIM, the perceptual hashes and the chroma term all see
    # the mask. The baseline capture is the coordinate reference (it's what
    # the user drew the region on).
    suppress_bboxes = suppress_bboxes or []
    if suppress_bboxes:
        reference = b_img
        b_img = _mask_regions(b_img, suppress_bboxes, reference)
        c_img = _mask_regions(c_img, suppress_bboxes, reference)

    # Grayscale views drive SSIM and the perceptual hashes exactly as
    # before; the RGB views feed only the chroma-shift term.
    b_gray = b_img.convert("L")
    c_gray = c_img.convert("L")

    w, h = _common_size(b_gray, c_gray)
    b_small = b_gray.resize((w, max(8, round(b_gray.height * (w / b_gray.width)))))
    c_small = c_gray.resize((w, max(8, round(c_gray.height * (w / c_gray.width)))))
    # Crop both to the shared top region (h = the shorter scaled height,
    # bounded): a page that merely grew taller compares its unchanged top,
    # while the whole-image perceptual hashes still see the full pages.
    b_arr = np.asarray(b_small, dtype=np.float64)[:h, :]
    c_arr = np.asarray(c_small, dtype=np.float64)[:h, :]

    b_rgb = np.asarray(
        b_img.resize((w, max(8, round(b_img.height * (w / b_img.width))))), dtype=np.float64
    )[:h, :, :]
    c_rgb = np.asarray(
        c_img.resize((w, max(8, round(c_img.height * (w / c_img.width))))), dtype=np.float64
    )[:h, :, :]
    chroma_mean_delta = float(np.max(np.abs(b_rgb.mean(axis=(0, 1)) - c_rgb.mean(axis=(0, 1)))))
    chroma_std_delta = float(np.max(np.abs(b_rgb.std(axis=(0, 1)) - c_rgb.std(axis=(0, 1)))))

    # data_range explicit: grayscale bytes span 0-255 (skimage docs warn
    # the float estimate would be wrong).
    ssim = float(structural_similarity(b_arr, c_arr, data_range=255.0))

    phash_b, phash_c = (
        imagehash.phash(b_gray, hash_size=HASH_SIZE),
        imagehash.phash(c_gray, hash_size=HASH_SIZE),
    )
    dhash_b, dhash_c = (
        imagehash.dhash(b_gray, hash_size=HASH_SIZE),
        imagehash.dhash(c_gray, hash_size=HASH_SIZE),
    )
    bits = HASH_SIZE * HASH_SIZE
    phash_dist = (phash_b - phash_c) / bits
    dhash_dist = (dhash_b - dhash_c) / bits

    # SSIM 1.0 -> identical. Dissimilarity maps to score; perceptual-hash
    # distance corroborates (weights favor SSIM, which sees layout). The
    # chroma term adds hue-only evidence the luminance channel cannot see,
    # deadbanded so render noise stays silent.
    ssim_score = max(0.0, min(1.0, 1.0 - ssim))
    hash_score = max(0.0, min(1.0, (phash_dist + dhash_dist)))  # each <= 0.5 realistically
    worst_chroma_delta = max(chroma_mean_delta, chroma_std_delta)
    chroma_score = min(
        1.0, max(0.0, (worst_chroma_delta - _CHROMA_DEADBAND_255)) / (255.0 - _CHROMA_DEADBAND_255)
    )
    score = min(1.0, 0.7 * ssim_score + 0.3 * hash_score + _W_CHROMA * chroma_score)

    evidence = {
        "ssim": round(ssim, 4),
        "phash_distance_bits": int(phash_b - phash_c),
        "dhash_distance_bits": int(dhash_b - dhash_c),
        "hash_bits": bits,
        "phash_distance_norm": round(phash_dist, 4),
        "dhash_distance_norm": round(dhash_dist, 4),
        "chroma_mean_delta_255": round(chroma_mean_delta, 2),
        "chroma_std_delta_255": round(chroma_std_delta, 2),
        "baseline_size": [b_img.width, b_img.height],
        "current_size": [c_img.width, c_img.height],
        "compared_size": [w, h],
    }
    if suppress_bboxes:
        evidence["suppressed_regions"] = [list(b) for b in suppress_bboxes[:20]]
    return layer_result(score, evidence)
