"""Wardress detection engine — the nine layers of master prompt §5.

Every layer is a discrete, independently testable function with the same
contract:

    layerN_xxx(baseline: PageData, current: ScanPageData) -> dict
    # returns {"score": float 0-1, "evidence": dict}

Layers never raise for bad *content* (malformed HTML, undecodable bytes,
missing artifacts are all legitimate observations about a possibly
defaced page) — content problems land in the evidence dict. Programming
errors still raise so tests catch them; the task wrapper's catch-all is
the last line of defense (rule 6).

Gating (cheaper layers gate expensive ones, §5) lives in pipeline.py —
the layer functions themselves are gate-free so each can be tested in
isolation.
"""

from worker.detection.types import PageData, ScanPageData, UAVariant, layer_result, skip_result

__all__ = [
    "PageData",
    "ScanPageData",
    "UAVariant",
    "layer_result",
    "skip_result",
]
