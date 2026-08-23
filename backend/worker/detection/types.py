"""Shared input/output shapes for the detection layers.

`PageData` is what both sides of every comparison look like: the layers
only ever see plain data (strings/bytes/dicts), never ORM rows or live
network handles — that's what makes each layer independently testable.
"""

import math
from dataclasses import dataclass, field


@dataclass
class PageData:
    """One captured page: the baseline side or the current-scan side."""

    html: str = ""
    screenshot: bytes = b""
    final_url: str = ""
    http_status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # Layer 6 inputs, gathered by the metadata prober (worker/probe.py):
    tls: dict | None = None  # not_after, fingerprint_sha256, subject, issuer...
    robots_txt: str | None = None
    content_hash: str = ""


@dataclass
class UAVariant:
    """One extra fetch under a rotated User-Agent (layer 7)."""

    ua_key: str  # "googlebot" | "mobile_safari" ...
    html: str = ""
    http_status: int | None = None
    final_url: str = ""
    error: str | None = None
    content_hash: str = ""


@dataclass
class ScanPageData(PageData):
    """The current-scan side: the primary fetch plus layer-7 UA variants."""

    ua_variants: list[UAVariant] = field(default_factory=list)


def layer_result(score: float, evidence: dict) -> dict:
    """The §5 contract: {"score": float 0-1, "evidence": dict}. Clamps
    defensively — a layer must never emit an out-of-range score.

    A NaN or infinite score is a numeric fault in the layer, not a signal.
    Because NaN fails every comparison, a plain min/max clamp would silently
    turn it into 1.0 — a max-severity result with no trace. Instead we treat
    it as 0.0 (no evidence of change) and record the fault in evidence so the
    bug is visible in the scan output rather than masquerading as an alarm."""
    numeric = float(score)
    if not math.isfinite(numeric):
        evidence = {**evidence, "score_fault": f"non-finite score {numeric!r} coerced to 0.0"}
        numeric = 0.0
    return {"score": max(0.0, min(1.0, numeric)), "evidence": evidence}


def skip_result(reason: str, **extra) -> dict:
    """A skipped layer still logs why (§5: 'always log that the layer was
    skipped and why'). Score None distinguishes 'not run' from 'ran, 0.0'.

    skip_result means "structurally nothing to measure" — the caller has a
    PROOF that the layer's value is zero (e.g. the identical-content-hash
    gate: byte-identical serialized DOM cannot produce structural, link,
    signature, or semantic deltas). For "tried to measure and could not",
    use degraded_result instead — fusion must not read a dark channel as a
    trusted zero."""
    return {"score": None, "skipped": True, "evidence": {"reason": reason, **extra}}


def degraded_result(reason: str, **extra) -> dict:
    """The capture/probe side failed: the layer TRIED to measure and could
    not. Score is None (no measurement exists), skipped=True (nothing was
    scored), and the top-level `degraded` flag marks it so fusion can treat
    the channel as UNKNOWN instead of evidence-of-zero — a missing
    screenshot or a dead metadata probe must never read exactly like a
    measured-identical page downstream."""
    return {
        "score": None,
        "skipped": True,
        "degraded": True,
        "evidence": {"reason": reason, **extra},
    }
