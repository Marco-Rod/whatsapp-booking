from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import ipaddress
import math
from threading import RLock
import time
from typing import Callable


@dataclass
class _Window:
    count: int
    expires_at: float


class FixedWindowRateLimiter:
    """A bounded, thread-safe fixed-window rate limiter."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        capacity: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit <= 0 or window_seconds <= 0 or capacity <= 0:
            raise ValueError("Rate limiter settings must be positive")

        self._limit = limit
        self._window_seconds = window_seconds
        self._capacity = capacity
        self._clock = clock
        self._windows: OrderedDict[str, _Window] = OrderedDict()
        self._next_expiry = math.inf
        self._lock = RLock()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._windows)

    def check(self, key: str) -> int | None:
        """Record one attempt and return retry seconds when it is rejected."""
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            window = self._windows.get(key)
            if window is None:
                if len(self._windows) >= self._capacity:
                    # Preserve availability for new clients while keeping memory bounded.
                    self._windows.popitem(last=False)
                window = _Window(count=0, expires_at=now + self._window_seconds)
                self._windows[key] = window
                self._next_expiry = min(self._next_expiry, window.expires_at)
            else:
                self._windows.move_to_end(key)

            if window.count >= self._limit:
                return max(1, math.ceil(window.expires_at - now))

            window.count += 1
            return None

    def _purge_expired(self, now: float) -> None:
        if now < self._next_expiry:
            return

        expired = [
            key
            for key, window in self._windows.items()
            if window.expires_at <= now
        ]
        for key in expired:
            del self._windows[key]
        self._next_expiry = min(
            (window.expires_at for window in self._windows.values()),
            default=math.inf,
        )


def normalize_client_ip(host: str | None) -> str:
    """Canonicalize IPv4 per address and IPv6 per /64 without proxy headers."""
    if not host:
        return "unknown"

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"

    if address.version == 4:
        return address.compressed
    return str(ipaddress.ip_network(f"{address}/64", strict=False))
