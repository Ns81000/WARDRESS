"""Shared scan/baseline lifecycle policy, used by both the API routers
and the Beat dispatcher so the two can never disagree about what counts
as "in flight".

In-flight rows older than STALE_INFLIGHT are treated as abandoned (the
Celery hard time limit is 360 s, so nothing legitimate runs this long).
Covers a worker killed too hard to run its failure handler, and rows
whose enqueue was lost. Without a cutoff, one orphaned row would block
that site's rebaseline/scan-now/auto-scans forever.
"""

from datetime import UTC, datetime, timedelta

STALE_INFLIGHT = timedelta(minutes=10)


def is_stale(created_at: datetime) -> bool:
    if created_at.tzinfo is None:  # SQLite test backend returns naive datetimes
        created_at = created_at.replace(tzinfo=UTC)
    return created_at < datetime.now(UTC) - STALE_INFLIGHT


# --- Adaptive scan intervals (§11) ---
# After a detected change the site is watched more closely; while stable
# the cadence relaxes back toward the user's configured base interval.
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 24 * 60
TIGHTEN_DIVISOR = 4  # change detected -> base/4 (floored at MIN)
RELAX_FACTOR = 1.5  # each clean scan -> current*1.5 (capped at base)

# Fused risk at/above this counts as a *material* change for scheduling.
# Deliberately lower than any sane flag threshold (watch real changes
# closely before they're alarming) but above dynamic-content noise —
# a page whose hash flips every scan (~0.03 risk) must still relax back
# to its base cadence, or "adaptive" would mean "permanently tightened".
MATERIAL_CHANGE_RISK = 0.15


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
