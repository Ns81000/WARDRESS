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

Scoring model (graded, direction-aware):

- Raw similarity is still token-set Jaccard on visible text; per-variant
  evidence keeps it unchanged.
- The score is graded from an *effective* divergence instead of a hard
  knee at union-divergence 0.5. A pure knee let crawlers be served up to
  ~50% foreign content at exactly 0.0 whenever the shared page vocabulary
  dominated the union (SEO-spam cloaking viable at scale while silent).
- The effective divergence takes the max of two complementary views:
  the symmetric union-relative Jaccard divergence (which saturates on
  total replacement even when the replacement page is small) and the
  *additive* new-token fraction |B∖A| / |A| relative to the reference
  (which punishes injected spam independent of how much shared base
  vocabulary dilutes the union).
- Divergence is routed by its dominant direction. Additive-dominant pairs
  (crawler served extra foreign content) ramp from 0.15; removal-dominant
  pairs keep a conservative ramp from 0.45, because servers legitimately
  adapt content down for mobile UAs and the layer must not punish normal
  responsive behavior.
- An absolute grace of _MIN_FOREIGN_TOKENS uniquely-differing tokens is
  applied before any grading: fewer than that is request-to-request churn
  (timestamps, counters, rotating widget text), and token-set counts on
  tiny pages exaggerate such edits into large relative divergences.

Failed variant fetches and bot-blocking (403/429, challenge pages) are
common and legitimate: they are recorded as evidence, not scored as
cloaking. That is a deliberate distinction from probe-side degradation —
when the rotation fetches never happened at all (no variants, or the
desktop reference itself unusable) the layer reports a degraded result
(score None) so fusion treats cloaking as UNKNOWN rather than as a
measured "no divergence"; a target that refuses bot UAs is a stable,
observed property, while a dead probe is our measurement being broken.

Multi-region fetch via proxy nodes (§5 optional) is not configured in
Phase 2 — the evidence notes it as unavailable.
"""

from worker.detection.signatures import extract_visible_text
from worker.detection.types import ScanPageData, UAVariant, degraded_result, layer_result

REFERENCE_UA_KEY = "desktop_chrome"

# Absolute grace (unique tokens): below this, divergence is dynamic churn,
# not a content campaign. Also neutralizes token-set Jaccard's exaggeration
# of trivial edits on short pages.
_MIN_FOREIGN_TOKENS = 12

# Ramp anchors over effective divergence (additive / removal channels).
_ADD_RAMP_LO = 0.15
_REMOVE_RAMP_LO = 0.45
_RAMP_HI = 0.85


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


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def _variant_cloak_score(ref_tokens: set[str], var_tokens: set[str]) -> tuple[float, dict]:
    """Grade one crawler-vs-reference token-set pair.

    Returns (score, diagnostics). Never raises on set inputs. The score is
    monotone non-decreasing in the amount of foreign content added, and 0.0
    for any pair whose absolute difference mass sits inside the churn grace.
    """
    added = len(var_tokens - ref_tokens)
    removed = len(ref_tokens - var_tokens)
    intersection = len(ref_tokens & var_tokens)
    union_size = len(ref_tokens | var_tokens)
    union_divergence = 1.0 - (intersection / union_size) if union_size else 0.0
    # Additive view relative to the REFERENCE size: immune to shared-base
    # dilution; clamped so massive injection saturates rather than escaping.
    new_token_fraction = min(1.0, added / max(1, len(ref_tokens)))

    detail = {
        "added_tokens": added,
        "removed_tokens": removed,
        "reference_tokens": len(ref_tokens),
        "union_divergence": round(union_divergence, 3),
        "new_token_fraction": round(new_token_fraction, 3),
    }

    if max(added, removed) <= _MIN_FOREIGN_TOKENS:
        detail["graced"] = True
        return 0.0, detail

    effective_additive = max(union_divergence, new_token_fraction)
    s_added = _clamp01((effective_additive - _ADD_RAMP_LO) / (_RAMP_HI - _ADD_RAMP_LO))
    s_removed = _clamp01((union_divergence - _REMOVE_RAMP_LO) / (_RAMP_HI - _REMOVE_RAMP_LO))
    score = s_removed if added == 0 else (s_added if added >= removed else s_removed)
    return score, detail


def layer7_cloaking(baseline: object, current: ScanPageData) -> dict:
    """`baseline` is unused (cloaking is an intra-scan comparison) but the
    signature keeps the §5 (baseline, current) contract."""
    variants = list(getattr(current, "ua_variants", None) or [])
    reference = next((v for v in variants if v.ua_key == REFERENCE_UA_KEY), None)
    rotated = [v for v in variants if v.ua_key != REFERENCE_UA_KEY]

    if reference is None or not rotated:
        return degraded_result(
            "UA-rotation fetches unavailable for this scan (probe degraded)",
            variants=[{"ua": v.ua_key, "error": v.error} for v in variants],
        )
    if not _usable(reference):
        return degraded_result(
            "reference (desktop UA) raw fetch not usable — cannot compare",
            reference_status=reference.http_status,
            reference_error=reference.error,
        )

    reference_text = extract_visible_text(reference.html)
    reference_tokens = set(reference_text.split())
    results = []
    worst_divergence = 0.0
    worst_variant_score = 0.0
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
                divergence = 1.0 - sim
                worst_divergence = max(worst_divergence, divergence)
                score, detail = _variant_cloak_score(
                    reference_tokens, set(extract_visible_text(v.html).split())
                )
                worst_variant_score = max(worst_variant_score, score)
                entry.update(detail)
        results.append(entry)

    return layer_result(
        min(1.0, max(0.0, worst_variant_score)),
        {
            "reference_ua": REFERENCE_UA_KEY,
            "variants": results,
            "worst_divergence": round(worst_divergence, 3),
            "scoring": {
                "model": "graded dual-channel (additive-fraction + union divergence)",
                "min_foreign_tokens": _MIN_FOREIGN_TOKENS,
                "additive_ramp": [_ADD_RAMP_LO, _RAMP_HI],
                "removal_ramp": [_REMOVE_RAMP_LO, _RAMP_HI],
            },
            "multi_region": "not configured (optional §5 feature; requires user proxy nodes)",
        },
    )
