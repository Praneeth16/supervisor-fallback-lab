"""A small in-process cache for read endpoints. Errors are not cached."""

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.ttl_s = ttl_s
        self._clock = clock
        self._items: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_load(self, key: Any, loader: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._items.get(key)
            if hit and now - hit[0] < self.ttl_s:
                return hit[1]
        value = loader()
        with self._lock:
            self._items[key] = (self._clock(), value)
        return value
