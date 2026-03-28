"""Fetch-through disk cache for map raster tiles (OSM + Esri World Imagery).

On fetch failure (network, rate limit, timeout), returns a tiny placeholder image
instead of raising — avoids 502 storms and blank Leaflet maps behind flaky links.
"""

from __future__ import annotations

import base64
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "SkydockLogServer/1.0 (tile cache; local use)"

OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ESRI_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

_LOG = logging.getLogger(__name__)

# 1×1 transparent PNG / minimal JPEG — used when upstream tile fetch fails
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PLACEHOLDER_JPG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRshMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k="
)

_FETCH_RETRIES = 3
_FETCH_TIMEOUT_S = 20.0


def _validate_xyz(z: int, x: int, y: int) -> None:
    if z < 0 or z > 22:
        raise ValueError("invalid z")
    n = 1 << z
    if x < 0 or x >= n or y < 0 or y >= n:
        raise ValueError("tile out of range")


def _fetch(url: str, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
        return resp.read()


def _fetch_with_retries(url: str, dest: Path) -> bytes | None:
    last_err: BaseException | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            return _fetch(url, dest)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                return None
            if attempt < _FETCH_RETRIES - 1 and e.code in (408, 429, 500, 502, 503, 504):
                time.sleep(0.4 * (attempt + 1))
                continue
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(0.2 * (attempt + 1))
                continue
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < _FETCH_RETRIES - 1:
                time.sleep(0.25 * (attempt + 1))
                continue
    if last_err:
        _LOG.warning("tile fetch failed %s: %s", url, last_err)
    return None


def get_osm_png(cache_root: Path, z: int, x: int, y: int) -> tuple[bytes, str]:
    _validate_xyz(z, x, y)
    rel = Path("osm") / str(z) / str(x) / f"{y}.png"
    dest = cache_root / rel
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes(), "image/png"
    url = OSM_URL.format(z=z, x=x, y=y)
    data = _fetch_with_retries(url, dest)
    if data is None:
        return _PLACEHOLDER_PNG, "image/png"
    try:
        dest.write_bytes(data)
    except OSError as e:
        _LOG.warning("tile cache write failed %s: %s", dest, e)
        return _PLACEHOLDER_PNG, "image/png"
    return data, "image/png"


def get_esri_jpg(cache_root: Path, z: int, y: int, x: int) -> tuple[bytes, str]:
    _validate_xyz(z, x, y)
    rel = Path("esri") / str(z) / str(y) / f"{x}.jpg"
    dest = cache_root / rel
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes(), "image/jpeg"
    url = ESRI_URL.format(z=z, y=y, x=x)
    data = _fetch_with_retries(url, dest)
    if data is None:
        return _PLACEHOLDER_JPG, "image/jpeg"
    try:
        dest.write_bytes(data)
    except OSError as e:
        _LOG.warning("tile cache write failed %s: %s", dest, e)
        return _PLACEHOLDER_JPG, "image/jpeg"
    return data, "image/jpeg"
