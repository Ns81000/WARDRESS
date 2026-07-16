"""Layer 7 — cloaking detection via User-Agent rotation (§5).

The metadata prober re-fetches the page over plain HTTP (httpx, no JS)
under three User-Agents: desktop Chrome (reference), Googlebot, and
mobile Safari. This layer compares what each rotated UA saw against the
desktop *reference* fetch — raw-vs-raw, apples to apples. Comparing a
raw fetch against the Playwright-rendered primary DOM would false-flag
every JS-heavy site, so the rendered capture is never used here.

A page that serves different content to a search-engine crawler than to
a browser UA is cloaking — a common way defacement/SEO-spam hides from
the site owner while poisoning search results.

Failed variant fetches and bot-blocking (403/429, challenge pages) are
common and legitimate: they are recorded as evidence, not scored as
cloaking. Only readable 2xx responses are compared for divergence.

Multi-region fetch via proxy nodes (§5 optional) is not configured in
Phase 2 — the evidence notes it as unavailable.
"""

from worker.detection.signatures import extract_visible_text
from worker.detection.types import ScanPageData, UAVariant, layer_result

REFERENCE_UA_KEY = "desktop_chrome"


def _text_similarity(a: str, b: str) -> float:
    """Cheap token-set overlap (Jaccard) on visible text — enough to
    grade 'same page, dynamic bits differ' vs 'entirely different page'."""
    ta, tb = set(a.split()), set(b.split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _usable(v: UAVariant) -> bool:
    return v.error is None and v.http_status is not None and 200 <= v.http_status < 300


def layer7_cloaking(baseline: object, current: ScanPageData) -> dict:
    """`baseline` is unused (cloaking is an intra-scan comparison) but the
    signature keeps the §5 (baseline, current) contract."""
    variants = list(getattr(current, "ua_variants", None) or [])
    reference = next((v for v in variants if v.ua_key == REFERENCE_UA_KEY), None)
    rotated = [v for v in variants if v.ua_key != REFERENCE_UA_KEY]

    if reference is None or not rotated:
        return layer_result(
            0.0,
            {
                "note": "UA-rotation fetches unavailable for this scan (probe degraded)",
                "variants": [{"ua": v.ua_key, "error": v.error} for v in variants],
            },
        )
    if not _usable(reference):
        return layer_result(
            0.0,
            {
                "note": "reference (desktop UA) raw fetch not usable — cannot compare",
                "reference_status": reference.http_status,
                "reference_error": reference.error,
            },
        )

    reference_text = extract_visible_text(reference.html)
    results = []
    worst_divergence = 0.0
    for v in rotated:
        entry: dict = {"ua": v.ua_key, "http_status": v.http_status}
        if not _usable(v):
            entry["comparable"] = False
            entry["error"] = v.error
            entry["note"] = "non-2xx/failed for this UA (bot blocking is common; not cloaking)"
        else:
            entry["comparable"] = True
            same_hash = (
                v.content_hash
                and reference.content_hash
                and v.content_hash == reference.content_hash
            )
            if same_hash:
                entry["identical_hash"] = True
                entry["similarity"] = 1.0
            else:
                sim = _text_similarity(reference_text, extract_visible_text(v.html))
                entry["identical_hash"] = False
                entry["similarity"] = round(sim, 3)
                worst_divergence = max(worst_divergence, 1.0 - sim)
        results.append(entry)

    # Mild dynamic variation stays at zero via the soft knee (token-set
    # Jaccard exaggerates small edits on short pages, so the knee sits at
    # 0.5); fully different content for some UA approaches 1.0.
    score = (worst_divergence - 0.5) / 0.5 if worst_divergence > 0.5 else 0.0
    return layer_result(
        min(1.0, max(0.0, score)),
        {
            "reference_ua": REFERENCE_UA_KEY,
            "variants": results,
            "worst_divergence": round(worst_divergence, 3),
            "multi_region": "not configured (optional §5 feature; requires user proxy nodes)",
        },
    )
