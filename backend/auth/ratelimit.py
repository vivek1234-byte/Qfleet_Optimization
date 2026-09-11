"""
Brute-force protection for the sign-in endpoint.

Without this, the login route is the weakest part of the system. bcrypt at
cost 12 takes about 250 ms, which sounds like a throttle until you notice that
nothing caps *concurrency*: a hundred parallel connections is four hundred
guesses a second, and an eight-character password does not survive that for
long. The same gap runs the other way as a denial of service — bcrypt is
deliberately CPU-expensive, so unauthenticated login spam pins every core and
takes the optimiser down with the login form.

Two keys, counted separately, because they defend against different attacks:

* **by Employee ID** — someone working through a password list against one
  known account. Locks that account's login attempts, from anywhere.
* **by client address** — someone spraying one common password across many
  Employee IDs. Per-account counters never trip; this one does.

Only *failures* count. A correct password clears both counters, so an employee
who mistypes twice and then gets it right is never delayed.

Deliberately in-memory. That is honest for one uvicorn worker and wrong behind
several — each process would keep its own counter and the effective limit
would multiply. `RateLimiter` is a plain class with no module-level state for
exactly that reason: swapping the store for Redis is replacing this file's
`_Bucket` dict, not rewriting the call sites.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from time import monotonic
from typing import Deque, Dict

from config import settings
from core.errors import AppError


class RateLimitedError(AppError):
    """Too many failed attempts. Carries the wait in ``Retry-After`` seconds."""

    status_code = 429
    code = "RATE_LIMITED"


class RateLimiter:
    """
    Sliding-window counter over recent failures.

    A window rather than a fixed lockout: a fixed lockout is a denial-of-service
    handed to the attacker, because anyone can lock any account out by failing
    against it deliberately. With a window the account frees itself, and the
    attacker's throughput is what stays capped.
    """

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        # uvicorn runs request handlers on a thread pool, so two failed logins
        # can touch the same deque at once.
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> Deque[float]:
        hits = self._hits[key]
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        if not hits:
            # Do not let the dict grow a key per address seen, ever.
            self._hits.pop(key, None)
        return hits

    def retry_after(self, key: str) -> int:
        """Seconds until `key` is allowed again; 0 when it is allowed now."""
        now = monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) < self.max_attempts:
                return 0
            return max(1, int(self.window_seconds - (now - hits[0])) + 1)

    def check(self, key: str) -> None:
        wait = self.retry_after(key)
        if wait:
            raise RateLimitedError(
                "Too many sign-in attempts. Wait a few minutes and try again.",
                details={"retry_after_seconds": wait},
            )

    def record_failure(self, key: str) -> None:
        now = monotonic()
        with self._lock:
            self._hits[key].append(now)
            self._prune(key, now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        """Drop every counter. For tests."""
        with self._lock:
            self._hits.clear()


# One limiter per axis. The per-address allowance is the looser of the two: a
# port office behind one NAT address is many legitimate people, and locking
# them out together would be worse than the attack.
by_employee = RateLimiter(
    max_attempts=settings.LOGIN_MAX_ATTEMPTS_PER_ID,
    window_seconds=settings.LOGIN_WINDOW_SECONDS,
)
by_address = RateLimiter(
    max_attempts=settings.LOGIN_MAX_ATTEMPTS_PER_IP,
    window_seconds=settings.LOGIN_WINDOW_SECONDS,
)


def guard(employee_id: str, address: str) -> None:
    """Refuse the attempt if either counter is over its limit."""
    by_employee.check(f"id:{employee_id}")
    by_address.check(f"ip:{address}")


def note_failure(employee_id: str, address: str) -> None:
    by_employee.record_failure(f"id:{employee_id}")
    by_address.record_failure(f"ip:{address}")


def note_success(employee_id: str, address: str) -> None:
    by_employee.clear(f"id:{employee_id}")
    by_address.clear(f"ip:{address}")


def reset_all() -> None:
    """For tests, and for an operator who has locked themselves out locally."""
    by_employee.reset()
    by_address.reset()
