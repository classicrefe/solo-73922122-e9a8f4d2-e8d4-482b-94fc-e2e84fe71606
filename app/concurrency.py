"""Per-ship locks.

Locks are intentionally keyed by ship: checking or correcting one ship never
takes a process-wide lock that blocks registration of another ship.  FastAPI
runs normal ``def`` endpoints in its worker thread pool, so these blocking
locks do not stall the async event loop.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class ShipLockManager:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, ship_code: str) -> threading.Lock:
        key = ship_code.strip()
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    @contextmanager
    def acquire(self, ship_code: str) -> Iterator[None]:
        lock = self.get(ship_code)
        with lock:
            yield


ship_locks = ShipLockManager()
