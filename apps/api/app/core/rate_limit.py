"""Sliding-window rate limiting for the auth surface.

A credential endpoint with no throttle is a password-oracle and a cheap DoS
target: an attacker can try logins as fast as the socket allows, and a few
hundred thousand guesses can be driven from one address. This is the smallest
policy that answers that — a per-client, sliding-window count that refuses with
``429`` once the window is full.

Design notes, stated because they are load-bearing:

* **In-process, not shared.** The counters live in this module's memory. That
  is correct for a single-node deployment and actively wrong behind a load
  balancer, where each process has its own window and the edge tells the truth.
  ``rate_limit_enabled`` and the two ``auth_rate_limit_*`` settings exist so an
  operator can move the policy outward without deleting the code.
* **No lock and no ``await`` between check and record.** ``check_rate_limit``
  is synchronous: it never yields to the event loop inside the window logic, so
  two coroutines cannot interleave there. That saves the cross-loop mess of a
  module-level ``asyncio.Lock`` (pytest-asyncio makes a fresh loop per test)
  while keeping the check-append atomic within one process.
* **Keyed by the caller-supplied address, documented as such.** Behind a proxy
  every request arrives from the proxy, so ``x-forwarded-for`` is preferred when
  present. Trusting a client-supplied header for *throttling* is safe (worst
  case an attacker throttles themselves); it only becomes dangerous when a
  header drives *authorization*, which it never does here.

Windows are evicted lazily: a stale hit is dropped only when the bucket is
touched again, and only while it is older than the window. Idle keys therefore
cost one dequeue entry each, which is a bounded, acceptable leak for an
application limiter.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from time import monotonic

from fastapi import Request

from app.core.errors import AppError

#: (bucket, client_key) -> ordered timestamps of accepted requests.
_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    """Drop every window. Used by the test harness between tests."""
    _buckets.clear()


def client_key(request: Request) -> str:
    """A stable identifier for one caller.

    Prefers ``x-forwarded-for`` so the limiter still groups a caller correctly
    when the API sits behind a proxy; falls back to the socket address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(
    bucket: str,
    key: str,
    *,
    max_requests: int,
    window_seconds: float,
) -> None:
    """Record a request and refuse it if the window is already full."""
    if max_requests <= 0:
        return
    now = monotonic()
    window = _buckets[(bucket, key)]
    while window and window[0] <= now - window_seconds:
        window.popleft()
    if len(window) >= max_requests:
        raise AppError(
            429,
            "RATE_LIMITED",
            "Too many attempts. Please wait before trying again.",
            headers={"Retry-After": str(int(window_seconds))},
        )
    window.append(now)


def rate_limit(bucket: str) -> Callable[[Request], None]:
    """FastAPI dependency: one fixed bucket name per endpoint.

    ``Depends(rate_limit("auth"))`` reads the auth settings, so the policy is
    configuration rather than a literal and can be tuned without a code change.
    """

    def _limit(request: Request) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        check_rate_limit(
            bucket,
            client_key(request),
            max_requests=settings.auth_rate_limit_max,
            window_seconds=settings.auth_rate_limit_window_seconds,
        )

    return _limit