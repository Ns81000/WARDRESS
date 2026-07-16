"""Content normalization + hashing — detection layer 1 building block.

Shared by baseline capture and scans so both sides hash identically.
Normalization is deliberately conservative: it removes only
representation noise (line endings, trailing whitespace, leading/trailing
blank lines), never content. Aggressive normalization would mask real
defacement; dynamic-content false positives are handled by suppression
rules (§5, Phase 3), not by hashing less.
"""

import hashlib


def normalize_content(html: str) -> str:
    lines = html.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized = "\n".join(line.rstrip() for line in lines)
    return normalized.strip("\n")


def content_sha256(html: str) -> str:
    return hashlib.sha256(normalize_content(html).encode("utf-8", errors="replace")).hexdigest()


def layer1_hash_diff(baseline_hash: str, current_hash: str) -> dict:
    """Layer 1 of §5: returns {score, evidence}. Score 0.0 = identical,
    1.0 = any difference (a hash can't grade partial change — later layers
    do that)."""
    identical = baseline_hash == current_hash
    return {
        "score": 0.0 if identical else 1.0,
        "evidence": {
            "baseline_sha256": baseline_hash,
            "current_sha256": current_hash,
            "identical": identical,
        },
    }
