from __future__ import annotations

from services.mission_cache import MissionReadCache


def test_lru_evicts_oldest() -> None:
    c = MissionReadCache(max_items=2)
    c.set(("a", 1), 1)
    c.set(("a", 2), 2)
    c.set(("a", 3), 3)
    assert c.get(("a", 1)) is None
    assert c.get(("a", 2)) == 2
    assert c.get(("a", 3)) == 3
