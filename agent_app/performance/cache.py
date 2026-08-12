from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock


@dataclass(slots=True)
class _CacheEntry[ValueT]:
    value: ValueT
    expires_at: float


class VersionedTTLCache[KeyT, ValueT]:
    """Small process-local LRU cache with explicit versioned keys."""

    def __init__(self, *, max_size: int, ttl_seconds: float) -> None:
        if max_size < 1:
            raise ValueError("max_size must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._values: OrderedDict[KeyT, _CacheEntry[ValueT]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: KeyT) -> ValueT | None:
        now = time.monotonic()
        with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._values.pop(key, None)
                return None
            self._values.move_to_end(key)
            return entry.value

    def put(self, key: KeyT, value: ValueT) -> None:
        with self._lock:
            self._values[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + self.ttl_seconds,
            )
            self._values.move_to_end(key)
            while len(self._values) > self.max_size:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)
