"""Unified LRU cache for mission log viewer derived payloads (summary, timeline, paths, FOV, etc.)."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class MissionReadCache:
    """Small process-local LRU keyed by arbitrary hashable tuples (e.g. ``(\"summary\", log_rev)``)."""

    def __init__(self, max_items: int = 64) -> None:
        self._d: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._max = max(1, int(max_items))

    def get(self, key: tuple[Any, ...]) -> Any | None:
        if key not in self._d:
            return None
        self._d.move_to_end(key)
        return self._d[key]

    def set(self, key: tuple[Any, ...], value: Any) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self._max:
            self._d.popitem(last=False)


# Shared instance for analysis + API route handlers.
MISSION_READ_CACHE = MissionReadCache(64)
