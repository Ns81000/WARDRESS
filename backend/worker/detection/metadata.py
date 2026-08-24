"""Layer 6 — security metadata diff (§5): TLS certificate, security
headers, robots.txt.

Compares what the metadata prober (worker/probe.py) captured for the
current scan against what the baseline stored:
- TLS: fingerprint change (reissue is normal near expiry; a fingerprint
  change with a *different issuer/subject* is more suspicious), expiry
  proximity, and validity window.
- Security headers: CSP/HSTS/X-Frame-Options/X-Content-Type-Options/
  Referrer-Policy/Permissions-Policy compared DIRECTIONALLY — removals
  and semantic regressions (a shorter HSTS max-age, CSP directives or
  tokens disappearing, X-Frame-Options DENY→SAMEORIGIN, a laxer
  referrer policy) score as downgrades; hardening is recorded but never
  penalized. Values that differ only in nonce/session-shaped components
  (per-response CSP nonces) or formatting compare as EQUAL, so
  nonce-deployed sites do not accrue noise on every scan. A value
  change whose direction cannot be determined semantically is recorded
  honestly but does not score.
- robots.txt content diff (defacers sometimes replace or delete it).

Missing probe data (site was HTTP-only, probe failed) is evidence, not
an error. A genuinely HTTP-only site has no TLS to compare — that is a
measured property, scored as stable-zero. But when the probe captured
nothing comparable at all (no TLS either side on a non-plain-HTTP pair,
and no header map on one side, and no robots signal), the layer reports
a degraded result so fusion treats metadata as UNKNOWN rather than as a
measured zero.
"""

import re

from worker.detection.types import PageData, degraded_result, layer_result

SECURITY_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
)

_HSTS_MAX_AGE_RE = re.compile(r"max-age\s*=\s*(\d+)", re.IGNORECASE)
_CSP_NONCE_RE = re.compile(r"'nonce-[^']*'")
# Per-response single-use values must never read as a header change.
_NORMALIZED_NONCE = "'nonce-'"
_XFO_STRENGTH = {"deny": 2, "sameorigin": 1}
# Ladder over exposure: higher = stricter. Multiple comma-separated
# policies resolve to the MOST PERMISSIVE recognized value, because that
# is the exposure a visitor actually gets.
_REFERRER_STRENGTH = {
    "no-referrer": 5,
    "same-origin": 4,
    "strict-origin": 4,
    "strict-origin-when-cross-origin": 3,
    "origin-when-cross-origin": 2,
    "origin": 2,
    "no-referrer-when-downgrade": 2,
    "unsafe-url": 0,
}


def _norm_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {k.lower(): v for k, v in (headers or {}).items()}


def _hsts_strength(value: str):
    """(max_age, includeSubDomains, preload) tuple — None when unparseable."""
    m = _HSTS_MAX_AGE_RE.search(value)
    if not m:
        return None
    lowered = value.lower()
    # Flags dominate any max-age difference: dropping includeSubDomains
    # (or preload) is a regression even alongside a bigger max-age.
    return (
        int(m.group(1))
        + (10**9 if "includesubdomains" in lowered else 0)
        + (10**10 if "preload" in lowered else 0)
    )


def _csp_directives(value: str) -> dict[str, frozenset[str]]:
    """directive name -> normalized token set. Nonce blobs are collapsed so
    per-response variance compares equal; case/whitespace normalized."""
    out: dict[str, frozenset[str]] = {}
    for part in value.split(";"):
        tokens = _CSP_NONCE_RE.sub(_NORMALIZED_NONCE, part).lower().split()
        if not tokens:
            continue
        out[tokens[0]] = frozenset(tokens[1:])
    return out


def _token_set(value: str) -> frozenset[str]:
    return frozenset(value.lower().replace("(", " ( ").replace(")", " ) ").split())


def _referrer_strength(value: str):
    strengths = [
        _REFERRER_STRENGTH[t]
        for t in (p.strip().lower() for p in value.split(","))
        if t in _REFERRER_STRENGTH
    ]
    return min(strengths) if strengths else None


def _classify_value_change(header: str, baseline: str, current: str):
    """ "weaker" | "stronger" | "equal" | None. "equal" means semantically
    identical once nonce/formatting noise is normalized away (never listed,
    never scored); None means a real value change whose direction cannot be
    determined semantically (recorded honestly, still never scored)."""
    if header == "strict-transport-security":
        b, c = _hsts_strength(baseline), _hsts_strength(current)
        if b is None or c is None:
            return None
        return "weaker" if c < b else ("stronger" if c > b else "equal")
    if header == "content-security-policy":
        b_dirs, c_dirs = _csp_directives(baseline), _csp_directives(current)
        weaker = stronger = False
        unknown = False
        for name in set(b_dirs) | set(c_dirs):
            b_toks, c_toks = b_dirs.get(name), c_dirs.get(name)
            if b_toks is None:
                stronger = True  # directive added
            elif c_toks is None:
                weaker = True  # directive removed
            elif c_toks != b_toks:
                if c_toks >= b_toks:
                    stronger = True
                elif b_toks >= c_toks:
                    weaker = True
                else:
                    unknown = True  # tokens exchanged — direction unclear
        if weaker:
            return "weaker"
        if unknown:
            return None
        return "stronger" if stronger else "equal"
    if header == "x-frame-options":
        b, c = (
            _XFO_STRENGTH.get(baseline.strip().lower()),
            _XFO_STRENGTH.get(current.strip().lower()),
        )
        if b is None or c is None:
            return None
        return "weaker" if c < b else ("stronger" if c > b else "equal")
    if header == "x-content-type-options":
        b, c = baseline.strip().lower() == "nosniff", current.strip().lower() == "nosniff"
        if b == c:
            return "equal"
        return "weaker" if b else "stronger"
    if header == "referrer-policy":
        b, c = _referrer_strength(baseline), _referrer_strength(current)
        if b is None or c is None:
            return None
        return "weaker" if c < b else ("stronger" if c > b else "equal")
    if header == "permissions-policy":
        # More allowlisted features/origins than the baseline = a laxer
        # policy (weaker); fewer = tighter.
        b_toks, c_toks = _token_set(baseline), _token_set(current)
        if c_toks == b_toks:
            return "equal"
        if b_toks < c_toks:
            return "weaker"
        if c_toks < b_toks:
            return "stronger"
        return None
    return None


def _tls_diff(baseline_tls: dict | None, current_tls: dict | None) -> tuple[float, dict]:
    if not baseline_tls and not current_tls:
        return 0.0, {"note": "no TLS data on either side (http site or probe unavailable)"}
    if baseline_tls and not current_tls:
        return 0.6, {
            "note": "baseline had TLS data but current probe returned none",
            "baseline_fingerprint": baseline_tls.get("fingerprint_sha256"),
        }
    if not baseline_tls and current_tls:
        return 0.0, {"note": "TLS data newly available (no baseline to compare)"}

    ev: dict = {}
    score = 0.0
    b_fp = baseline_tls.get("fingerprint_sha256")
    c_fp = current_tls.get("fingerprint_sha256")
    ev["fingerprint_changed"] = bool(b_fp and c_fp and b_fp != c_fp)
    if ev["fingerprint_changed"]:
        b_issuer = baseline_tls.get("issuer")
        c_issuer = current_tls.get("issuer")
        b_subject = baseline_tls.get("subject")
        c_subject = current_tls.get("subject")
        ev["issuer_changed"] = b_issuer != c_issuer
        ev["subject_changed"] = b_subject != c_subject
        ev["baseline_issuer"], ev["current_issuer"] = b_issuer, c_issuer
        ev["baseline_subject"], ev["current_subject"] = b_subject, c_subject
        if ev["issuer_changed"] or ev["subject_changed"]:
            # New cert from a different CA or for different names — the
            # interesting case (MITM/hijack or migration).
            score = 0.55
        else:
            # Routine reissue: same issuer, same subject.
            score = 0.1
    ev["baseline_not_after"] = baseline_tls.get("not_after")
    ev["current_not_after"] = current_tls.get("not_after")
    if current_tls.get("expired"):
        ev["expired"] = True
        score = max(score, 0.5)
    return score, ev


def _header_diff(
    baseline_headers: dict[str, str], current_headers: dict[str, str]
) -> tuple[float, dict]:
    # An empty header map means that side's probe didn't capture headers
    # (probe degraded, or a Phase 1-era baseline). Comparing full headers
    # against nothing would report every security header as "removed" —
    # a false positive. Unavailable is a note, not a downgrade.
    if not baseline_headers or not current_headers:
        return 0.0, {
            "note": "header capture unavailable on one side — comparison skipped",
            "baseline_headers_available": bool(baseline_headers),
            "current_headers_available": bool(current_headers),
        }
    removed = []
    weakened = []
    strengthened = []
    undirected = []
    added = []
    for h in SECURITY_HEADERS:
        b, c = baseline_headers.get(h), current_headers.get(h)
        if b and not c:
            removed.append(h)
        elif not b and c:
            added.append(h)
        elif b and c and b != c:
            entry = {"header": h, "baseline": b[:300], "current": c[:300]}
            verdict = _classify_value_change(h, b, c)
            if verdict == "weaker":
                weakened.append(entry)
            elif verdict == "stronger":
                strengthened.append(entry)
            elif verdict == "equal":
                pass  # semantically identical once nonce/format noise is normalized
            else:
                # A real value change whose direction cannot be determined —
                # recorded honestly, never scored either way.
                undirected.append(entry)
    # Each removed security header is a meaningful downgrade; each
    # semantic regression adds less. Hardening and unclassifiable value
    # changes never score.
    score = min(0.8, 0.3 * len(removed) + 0.1 * len(weakened))
    return score, {
        "security_headers_removed": removed,
        "security_headers_weakened": weakened,
        "security_headers_strengthened": strengthened,
        "security_headers_changed": undirected,
        "security_headers_added": added,
    }


def _robots_diff(baseline_robots: str | None, current_robots: str | None) -> tuple[float, dict]:
    if baseline_robots is None and current_robots is None:
        return 0.0, {"note": "robots.txt unavailable on both sides"}
    if (baseline_robots or "") == (current_robots or ""):
        return 0.0, {"changed": False}
    b_lines = set((baseline_robots or "").splitlines())
    c_lines = set((current_robots or "").splitlines())
    return 0.15, {
        "changed": True,
        "lines_added": sorted(c_lines - b_lines)[:30],
        "lines_removed": sorted(b_lines - c_lines)[:30],
        "baseline_missing": baseline_robots is None,
        "current_missing": current_robots is None,
    }


def layer6_security_metadata(baseline: PageData, current: PageData) -> dict:
    # A plain-HTTP site (both final URLs http://) genuinely has no TLS:
    # absent cert data is the measured truth, not a broken probe. Any
    # other scheme — or an unknown one (legacy baselines) — leaves TLS
    # unmeasurable when both sides lack cert data.
    b_http = (baseline.final_url or "").lower().startswith("http://")
    c_http = (current.final_url or "").lower().startswith("http://")
    tls_unmeasured = not baseline.tls and not current.tls and not (b_http and c_http)
    headers_unmeasured = not baseline.headers or not current.headers
    robots_signal = (baseline.robots_txt or "") != (current.robots_txt or "")

    if tls_unmeasured and headers_unmeasured and not robots_signal:
        # Every channel is dark: nothing here was measured. A real robots
        # change still rescues the layer below — it carries signal even
        # when TLS/headers could not be captured.
        return degraded_result(
            "security-metadata probe captured no comparable data on either side",
            tls_available=bool(baseline.tls or current.tls),
            headers_available=bool(baseline.headers and current.headers),
        )

    tls_score, tls_ev = _tls_diff(baseline.tls, current.tls)
    hdr_score, hdr_ev = _header_diff(
        _norm_headers(baseline.headers), _norm_headers(current.headers)
    )
    robots_score, robots_ev = _robots_diff(baseline.robots_txt, current.robots_txt)

    # Independent weak signals combine, capped: metadata alone should
    # push a scan into "worth a look", not into "confirmed defacement".
    score = min(1.0, tls_score + hdr_score + robots_score)
    return layer_result(
        score,
        {"tls": tls_ev, "headers": hdr_ev, "robots_txt": robots_ev},
    )
