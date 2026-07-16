"""Layer 6 — security metadata diff (§5): TLS certificate, security
headers, robots.txt.

Compares what the metadata prober (worker/probe.py) captured for the
current scan against what the baseline stored:
- TLS: fingerprint change (reissue is normal near expiry; a fingerprint
  change with a *different issuer/subject* is more suspicious), expiry
  proximity, and validity window.
- Security headers: CSP/HSTS/X-Frame-Options/X-Content-Type-Options/
  Referrer-Policy disappearing or weakening (headers *appearing* is an
  improvement, not a threat).
- robots.txt content diff (defacers sometimes replace or delete it).

Missing probe data (site was HTTP-only, probe failed) is evidence, not
an error — the layer scores what it can see.
"""

from worker.detection.types import PageData, layer_result

SECURITY_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "permissions-policy",
)


def _norm_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return {k.lower(): v for k, v in (headers or {}).items()}


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
    added = []
    for h in SECURITY_HEADERS:
        b, c = baseline_headers.get(h), current_headers.get(h)
        if b and not c:
            removed.append(h)
        elif not b and c:
            added.append(h)
        elif b and c and b != c:
            weakened.append({"header": h, "baseline": b[:300], "current": c[:300]})
    # Each removed security header is a meaningful downgrade.
    score = min(0.8, 0.3 * len(removed) + 0.1 * len(weakened))
    return score, {
        "security_headers_removed": removed,
        "security_headers_changed": weakened,
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
