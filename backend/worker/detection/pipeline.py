"""Detection pipeline — runs layers 1-9 in §5 order with gating.

Gating rules (cheaper layers gate more expensive ones; every skip is
logged with its reason as a §5 requirement):
- Layer 1 (hash) runs always. If the hash is IDENTICAL, layers 2-5 and 8
  are skipped (byte-identical content cannot differ structurally,
  in links, visually*, in signatures, or semantically) — recorded as
  skip results, score None.
  *Layer 4 is also skipped on identical hash: the screenshot could only
  differ through non-deterministic rendering noise, which is exactly the
  false-positive class the gate exists to suppress.
- Layers 6 (metadata) and 7 (cloaking) run regardless of layer 1: TLS/
  header downgrades and per-UA divergence are invisible to the primary
  content hash.
- Layer 9 (fusion) always runs, over whatever the other layers produced.

Each layer is individually crash-isolated: a layer that raises
unexpectedly is recorded as failed evidence (score None, skipped=True,
reason=internal error) and the pipeline continues — one broken parser
must never blind the other eight layers (rule 6).
"""

import logging

from worker.detection.cloaking import layer7_cloaking
from worker.detection.dom import layer2_dom_structure, layer3_link_audit
from worker.detection.fusion import layer9_fusion
from worker.detection.metadata import layer6_security_metadata
from worker.detection.semantics import layer8_semantics
from worker.detection.signatures import layer5_signatures
from worker.detection.types import PageData, ScanPageData, skip_result
from worker.hashing import layer1_hash_diff

logger = logging.getLogger(__name__)

# (layer number, stable key) in §5 order. Keys never change once shipped —
# scan_findings rows and the fusion feature order both depend on them.
LAYERS = [
    (1, "layer1_hash"),
    (2, "layer2_dom_structure"),
    (3, "layer3_link_audit"),
    (4, "layer4_visual_diff"),
    (5, "layer5_signatures"),
    (6, "layer6_security_metadata"),
    (7, "layer7_cloaking"),
    (8, "layer8_semantics"),
    (9, "layer9_fusion"),
]

GATED_BY_IDENTICAL_HASH = {
    "layer2_dom_structure",
    "layer3_link_audit",
    "layer4_visual_diff",
    "layer5_signatures",
    "layer8_semantics",
}

_LAYER_FUNCS = {
    "layer2_dom_structure": layer2_dom_structure,
    "layer3_link_audit": layer3_link_audit,
    "layer4_visual_diff": None,  # imported lazily — pulls numpy/skimage
    "layer5_signatures": layer5_signatures,
    "layer6_security_metadata": layer6_security_metadata,
    "layer7_cloaking": layer7_cloaking,
    "layer8_semantics": layer8_semantics,
}


def _visual_diff(baseline: PageData, current: PageData) -> dict:
    from worker.detection.visual import layer4_visual_diff

    return layer4_visual_diff(baseline, current)


def run_detection(baseline: PageData, current: ScanPageData) -> dict[str, dict]:
    """Run every layer with gating. Returns {layer_key: result} where each
    result is {"score": float|None, "evidence": dict, "skipped"?: True}."""
    results: dict[str, dict] = {}

    # Layer 1 — always.
    results["layer1_hash"] = layer1_hash_diff(baseline.content_hash, current.content_hash)
    identical = results["layer1_hash"]["score"] == 0.0

    # A baseline whose HTML artifact is unavailable (volume moved, file
    # lost) can still hash-compare via the stored digest, but the
    # content-comparing layers would see an empty baseline and false-flag
    # everything — skip them with the real reason instead.
    baseline_html_missing = not baseline.html.strip()

    for number, key in LAYERS:
        if key in results or key == "layer9_fusion":
            continue
        if identical and key in GATED_BY_IDENTICAL_HASH:
            results[key] = skip_result(
                "gated by layer 1: content hash identical, layer cannot produce new signal"
            )
            continue
        if baseline_html_missing and key in GATED_BY_IDENTICAL_HASH and key != "layer4_visual_diff":
            results[key] = skip_result(
                "baseline HTML artifact unavailable — content comparison impossible"
            )
            continue
        func = _visual_diff if key == "layer4_visual_diff" else _LAYER_FUNCS[key]
        try:
            results[key] = func(baseline, current)
        except Exception as exc:
            # One broken layer must not blind the rest (rule 6).
            logger.exception("Layer %s (%s) failed", number, key)
            results[key] = skip_result(
                "layer failed unexpectedly — see worker logs",
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )

    results["layer9_fusion"] = layer9_fusion(results)
    return results
