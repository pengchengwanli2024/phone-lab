"""In-memory admission for read-only phone captures; never queues device work.

Inspired by OpenMausBot's shared preview budget and failure backoff. Implemented
for the existing Python phone fleet; no upstream runtime or code is embedded.
"""
from dataclasses import dataclass
import threading
import time
from typing import Callable

CAPTURE_RATE = 4.0
CAPTURE_CONCURRENCY = 3
DEMAND_SECONDS = 6.0
BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 120.0


@dataclass(eq=False)
class _Capture:
    key: str
    current: bool = True


class FrameCapturePolicy:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._tokens = CAPTURE_RATE
        self._refilled = clock()
        self._active: dict[str, _Capture] = {}
        self._failures: dict[str, tuple[int, float]] = {}
        self._waiting: dict[str, float] = {}
        self._closed = False

    def begin(self, key: str) -> _Capture | None:
        with self._lock:
            now = self._clock()
            if self._closed or key in self._active:
                return None
            if now < self._failures.get(key, (0, 0.0))[1]:
                return None
            self._waiting = {name: seen for name, seen in self._waiting.items() if now - seen < DEMAND_SECONDS}
            # Remember demand, not runnable work: an admission still requires a
            # new frame request. Fast pollers cannot starve the later phones.
            self._waiting[key] = now
            if (len(self._active) >= CAPTURE_CONCURRENCY
                    or key not in tuple(self._waiting)[:CAPTURE_CONCURRENCY - len(self._active)]):
                return None
            self._tokens = min(CAPTURE_RATE, self._tokens + max(0.0, now - self._refilled) * CAPTURE_RATE)
            self._refilled = now
            if self._tokens < 1:
                return None
            self._tokens -= 1
            self._waiting.pop(key)
            ticket = _Capture(key)
            self._active[key] = ticket
            return ticket

    def finish(self, ticket: _Capture, *, success: bool) -> bool:
        with self._lock:
            if self._active.get(ticket.key) is not ticket:
                return False
            del self._active[ticket.key]
            if self._closed or not ticket.current:
                return False
            if success:
                self._failures.pop(ticket.key, None)
            else:
                count = min(6, self._failures.get(ticket.key, (0, 0.0))[0] + 1)
                delay = min(MAX_BACKOFF_SECONDS, BACKOFF_SECONDS * 2 ** (count - 1))
                self._failures[ticket.key] = (count, self._clock() + delay)
            return True

    def forget(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._waiting.pop(key, None)
            ticket = self._active.get(key)
            if ticket:
                # An unplugged device's subprocess still occupies its slot.
                # Releasing it early would let reconnects exceed the global cap.
                ticket.current = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._failures.clear()
            self._waiting.clear()
            for ticket in self._active.values():
                ticket.current = False
