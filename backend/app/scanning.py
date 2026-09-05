"""Shared scan/baseline lifecycle policy, used by both the API routers
and the Beat dispatcher so the two can never disagree about what counts
as "in flight".

In-flight rows older than STALE_INFLIGHT are treated as abandoned (the
Celery hard time limit is 480 s, so nothing legitimate runs this long).
Covers a worker killed too hard to run its failure handler, and rows
whose enqueue was lost. Without a cutoff, one orphaned row would block
that site's rebaseline/scan-now/auto-scans forever.
"""

from datetime import UTC, datetime, timedelta

STALE_INFLIGHT = timedelta(minutes=10)


def is_stale(created_at: datetime, started_at: datetime | None = None) -> bool:
    """True when an in-flight scan/baseline has been running too long.

    Measures from `started_at` when the worker has picked it up (status
    running), otherwise from `created_at` (still pending). Using created_at
    for a running scan would falsely expire a backlogged-then-running scan
    that spent most of its age waiting in the queue.
    """
    anchor = started_at if started_at is not None else created_at
    if anchor.tzinfo is None:  # SQLite test backend returns naive datetimes
        anchor = anchor.replace(tzinfo=UTC)
    return anchor < datetime.now(UTC) - STALE_INFLIGHT


# --- Adaptive scan intervals (§11) ---
# After a detected change the site is watched more closely; while stable
# the cadence relaxes back toward the user's configured base interval.
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 24 * 60
TIGHTEN_DIVISOR = 4  # change detected -> base/4 (floored at MIN)
RELAX_FACTOR = 1.5  # each clean scan -> current*1.5 (capped at base)

# Fused risk at/above this counts as a *material* change for scheduling.
# Deliberately aligned with the LLM escalation floor (worker/
# llm_escalation.ESCALATION_LOW): "the local layers want a second opinion"
# is the same bar as "worth watching more closely". It must sit ABOVE the
# fused risk that pure dynamic-content noise produces under the deployed
# fusion model — re-measured on the full benign-dynamic corpus with the
# CURRENT layer code after PROMPT-002 Phases 8-10 (volatile-text + CSP
# nonce normalization, layer-2 content-aware churn weighting; Phase 11
# session): rotating ads, timestamps/counters, cache-busting refs, CSS
# churn and mixed noise fuse to ~0.14-0.15 (unchanged-or-lower vs the
# post-regeneration measurements), editorial rewrites to ~0.30. The one
# axis that moved UP is A/B hero swaps: normalization made layer 8's
# semantic comparison more honest on the swapped content, pushing 3/22
# rows to ~0.43-0.44 — genuine content deltas that legitimately tighten
# cadence briefly (a same-variant rescan reads clean and relaxes back),
# not enough to justify decoupling this bar from the 0.40 escalation
# floor and the new-domain-infrastructure rule floor. (Heavy legitimate
# restructuring — site redesigns, vendor script additions — legitimately
# crosses this bar; something big DID happen.)
MATERIAL_CHANGE_RISK = 0.40


def clamp_interval(minutes: int) -> int:
    return max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, minutes))


def next_interval_after_scan(base_minutes: int, current_minutes: int | None, changed: bool) -> int:
    """The adaptive cadence: tighten sharply on a detected change, relax
    gradually (x1.5 per clean scan) back up to the configured base."""
    base = clamp_interval(base_minutes)
    if changed:
        return clamp_interval(base // TIGHTEN_DIVISOR)
    current = clamp_interval(current_minutes or base)
    if current >= base:
        return base
    return min(base, clamp_interval(round(current * RELAX_FACTOR)))
