"""In-process API rate limiting (§9: per-user and per-IP).

A single-host self-hosted deployment has exactly one API process, so an
in-memory fixed-window counter is sufficient and needs no Redis round
trip on the hot path. Two independent limits:

- **per-IP** — enforced in middleware before authentication, so
  unauthenticated floods (login attempts, probing) are capped too. Keyed
  on the best-effort client IP.
- **per-user** — enforced in the auth dependency once the caller is
  known, keyed on the user id, so one noisy account can't crowd out
  others regardless of source IP.

Both raise HTTP 429 with a `Retry-After` header. Limits are generous by
default (a monitoring dashboard is not a public API) and configurable via
env. The store is trimmed opportunistically so idle keys don't leak
memory. Deliberate non-goal: distributed accuracy — there is one process.
"""

import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.config import get_settings


@dataclass
class _Window:
    count: int
    reset_at: float


class FixedWindowLimiter:
    """Fixed-window counter: `limit` events per `window_seconds` per key."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._buckets: dict[str, _Window] = {}
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def _sweep(self, now: float) -> None:
        # Drop expired windows every ~window seconds to bound memory.
        if now - self._last_sweep < self.window:
            return
        self._last_sweep = now
        expired = [k for k, w in self._buckets.items() if w.reset_at <= now]
        for k in expired:
            del self._buckets[k]

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). Counts the event when
        allowed."""
        if self.limit <= 0:  # 0/negative disables the limit
            return True, 0
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            window = self._buckets.get(key)
            if window is None or window.reset_at <= now:
                self._buckets[key] = _Window(count=1, reset_at=now + self.window)
                return True, 0
            if window.count >= self.limit:
                return False, max(1, int(window.reset_at - now))
            window.count += 1
            return True, 0


_per_ip: FixedWindowLimiter | None = None
_per_user: FixedWindowLimiter | None = None


def _limiters() -> tuple[FixedWindowLimiter, FixedWindowLimiter]:
    global _per_ip, _per_user
    if _per_ip is None or _per_user is None:
        s = get_settings()
        _per_ip = FixedWindowLimiter(s.rate_limit_per_ip, s.rate_limit_window_seconds)
        _per_user = FixedWindowLimiter(s.rate_limit_per_user, s.rate_limit_window_seconds)
    return _per_ip, _per_user


def reset_limiters() -> None:
    """Test hook: forget accumulated state and rebuild from current env."""
    global _per_ip, _per_user
    _per_ip = None
    _per_user = None


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honors X-Forwarded-For only when the app is
    configured to trust a proxy (self-hosted default: don't — the socket
    peer is authoritative and unspoofable)."""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _raise_429(retry_after: int) -> None:
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Rate limit exceeded — slow down and retry shortly",
        headers={"Retry-After": str(retry_after)},
    )


def enforce_ip_rate_limit(request: Request) -> None:
    per_ip, _ = _limiters()
    allowed, retry_after = per_ip.check(f"ip:{client_ip(request)}")
    if not allowed:
        _raise_429(retry_after)


def enforce_user_rate_limit(request: Request, user_id: str) -> None:
    _, per_user = _limiters()
    allowed, retry_after = per_user.check(f"user:{user_id}")
    if not allowed:
        _raise_429(retry_after)
