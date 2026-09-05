"""Capture-method version — the migration gate between capture flows
(PROMPT-002 Phase 7).

Lives app-side on purpose: the API process must never import worker code
(Playwright et al. — see app/tasks.py), but both sides need the constant.
The worker stamps it into every capture's capture_evidence and every
baseline's capture_meta (worker/scan_tasks.py); the API compares a site's
current baseline version against it to drive the re-baseline hint
(routers/sites.py) — an old-method baseline makes the first post-upgrade
scans flag one-time structural deltas (scroll depth, banner state) as
changes until the site is re-baselined.

Bump whenever the capture flow changes in a way that makes captures
structurally incomparable with older ones (a new preparation pass, new
suppression steps, changed screenshot semantics). Never decrement.
"""

CAPTURE_METHOD_VERSION = 1
