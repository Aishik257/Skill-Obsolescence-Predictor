"""Tiny thread-safe TTL cache for filtered analytics (cleared whenever data or analysis changes)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 256):
        self.ttl, self.max_items = ttl_seconds, max_items
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: Any, factory: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = factory()
        with self._lock:
            if len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (time.monotonic(), value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


analysis_cache = TTLCache()
