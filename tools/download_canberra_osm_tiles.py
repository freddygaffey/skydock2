#!/usr/bin/env python3
"""
Download map raster tiles for the Canberra (ACT) region for offline / local Leaflet use.

The log viewer loads OSM/Esri tiles **directly in the browser**; this script is optional
**bulk** raster download for offline folders or static hosting.

Sources:
  osm  — OpenStreetMap standard map (PNG). Policy:
         https://operations.osmfoundation.org/policies/tiles/
  esri — Esri World Imagery (satellite, JPEG), same endpoint as the log server “Satellite”
         layer. Use per Esri / ArcGIS Online terms and keep attribution on the map.

Layout on disk (Leaflet-compatible): <out_dir>/{z}/{x}/{y}.<ext>

Use ``--dry-run`` to preview. A real download asks ``Proceed? [y/N]`` unless you pass ``--yes``.
Use ``--target-hours 7`` to pace requests so the job lasts about that long (overrides ``--sleep``).

Esri satellite default is z10–z19 (~46 GB ballpark for the default Canberra bbox). Use
``--max-zoom 20`` or ``21`` if you want even finer detail (much larger on disk).

OpenStreetMap defaults stay moderate to reduce load on OSM’s volunteer tile servers.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# West, South, East, North (degrees) — greater Canberra / ACT + immediate surrounds
DEFAULT_BBOX = (148.90, -35.98, 149.52, -35.12)

USER_AGENT = "SkydockLocalTileCache/1.0 (private offline cache)"

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
# Same template as tools/log_server mission_dashboard.html satellite layer
ESRI_TILE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)


def lon2tile(lon: float, zoom: int) -> int:
    return int((lon + 180.0) / 360.0 * (1 << zoom))


def lat2tile(lat: float, zoom: int) -> int:
    lat_rad = math.radians(lat)
    return int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * (1 << zoom)
    )


def tile_range_for_bbox(
    west: float, south: float, east: float, north: float, zoom: int
) -> tuple[int, int, int, int]:
    x_min = lon2tile(west, zoom)
    x_max = lon2tile(east, zoom)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    y_n = lat2tile(north, zoom)
    y_s = lat2tile(south, zoom)
    y_min = min(y_n, y_s)
    y_max = max(y_n, y_s)
    return x_min, x_max, y_min, y_max


def count_tiles(
    west: float, south: float, east: float, north: float, zmin: int, zmax: int
) -> int:
    n = 0
    for z in range(zmin, zmax + 1):
        xa, xb, ya, yb = tile_range_for_bbox(west, south, east, north, z)
        n += (xb - xa + 1) * (yb - ya + 1)
    return n


def tile_url(source: str, z: int, x: int, y: int) -> str:
    if source == "esri":
        return ESRI_TILE_URL.format(z=z, y=y, x=x)
    return OSM_TILE_URL.format(z=z, x=x, y=y)


def default_out_dir(source: str) -> Path:
    base = Path(__file__).resolve().parents[1] / "data"
    name = "esri_canberra_tiles" if source == "esri" else "osm_canberra_tiles"
    return base / name


def default_max_zoom(source: str) -> int:
    # Esri: z19 ≈ ~46 GB for default Canberra bbox; z20+ is much larger.
    # OSM: stay at z17 — bulk high‑zoom OSM downloads stress openstreetmap.org.
    return 19 if source == "esri" else 17


def default_sleep(source: str) -> float:
    return 0.12 if source == "osm" else 0.08


def main() -> int:
    p = argparse.ArgumentParser(
        description="Download OSM or Esri World Imagery tiles for the Canberra region."
    )
    p.add_argument(
        "--source",
        choices=("osm", "esri"),
        default="osm",
        help="osm = street map; esri = satellite (World Imagery)",
    )
    p.add_argument(
        "--bbox",
        default=",".join(str(x) for x in DEFAULT_BBOX),
        help="west,south,east,north in degrees (default: Canberra ACT area)",
    )
    p.add_argument("--min-zoom", type=int, default=10, help="minimum zoom (default 10)")
    p.add_argument(
        "--max-zoom",
        type=int,
        default=None,
        help="maximum zoom (default 17 osm, 19 esri ≈46 GB Canberra bbox). Use 20–21 for finer satellite.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output directory (default: data/osm_canberra_tiles or data/esri_canberra_tiles)",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="seconds to pause after each request (default: 0.12 osm, 0.08 esri); ignored if --target-hours set",
    )
    p.add_argument(
        "--target-hours",
        type=float,
        default=None,
        metavar="H",
        help="pace so total wall time is about H hours (sets pause from tile count; overrides --sleep)",
    )
    p.add_argument(
        "--http-sec",
        type=float,
        default=0.18,
        help="assumed average HTTP time per tile when using --target-hours (default 0.18)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print tile counts only, do not download",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="skip the interactive confirmation prompt (also required if tiles > 8,000,000)",
    )
    args = p.parse_args()

    src = args.source
    max_z = args.max_zoom if args.max_zoom is not None else default_max_zoom(src)
    out_dir = args.out_dir if args.out_dir is not None else default_out_dir(src)
    ext = "jpg" if src == "esri" else "png"

    parts = [float(x.strip()) for x in args.bbox.split(",")]
    if len(parts) != 4:
        print("bbox must be west,south,east,north", file=sys.stderr)
        return 2
    west, south, east, north = parts

    z_cap = 22 if src == "esri" else 19
    if args.min_zoom < 0 or max_z > z_cap or args.min_zoom > max_z:
        print(f"invalid zoom range (use 0–{z_cap} for {src}, min<=max)", file=sys.stderr)
        return 2

    total = count_tiles(west, south, east, north, args.min_zoom, max_z)
    # Rough size hint (~25 KB JPEG, ~15 KB PNG average; very approximate)
    kb_per = 25 if ext == "jpg" else 15
    approx_gb = total * kb_per / 1_000_000

    if args.target_hours is not None and total > 0:
        sec_budget = args.target_hours * 3600.0 / total
        hs = args.http_sec
        if sec_budget <= hs:
            est_h = total * hs / 3600.0
            print(
                f"Pacing: cannot hit ~{args.target_hours}h — sequential HTTP needs ~{est_h:.1f}h minimum "
                f"(at ~{hs}s/tile). Using minimal pause; use a smaller bbox/zoom or a longer --target-hours.\n",
                file=sys.stderr,
            )
            sleep = 0.001
        else:
            sleep = sec_budget - hs
        est_wall_h = total * (sleep + hs) / 3600.0
        pacing_line = (
            f"Pacing: ~{args.target_hours}h target → {sleep:.4f}s pause after each tile "
            f"(~{hs}s HTTP assumed) → est. ~{est_wall_h:.1f}h wall if every tile is fetched"
        )
    elif args.sleep is not None:
        sleep = args.sleep
        pacing_line = None
    else:
        sleep = default_sleep(src)
        pacing_line = None

    print(f"Source: {src.upper()}  ({'Esri World Imagery' if src == 'esri' else 'OpenStreetMap'})")
    print(f"BBox: W={west} S={south} E={east} N={north}")
    print(f"Zoom: {args.min_zoom}..{max_z}  →  {total:,} tiles  (~{approx_gb:.0f} GB ballpark)")
    print(f"Output: {out_dir}  (.{ext})")
    if pacing_line:
        print(pacing_line)
    else:
        print(f"Pause: {sleep:.4f}s after each request (use --target-hours H to aim for ~H hours wall time)")

    if args.dry_run:
        return 0

    EXTREME_TILES = 8_000_000
    if total > EXTREME_TILES and not args.yes:
        print(
            f"\nOver {EXTREME_TILES:,} tiles — likely weeks of runtime. Narrow --bbox or lower --max-zoom,\n"
            f"or pass --yes to confirm without a prompt.\n",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        try:
            ans = input("Proceed with download? [y/N]: ").strip().lower()
        except EOFError:
            print("Non-interactive shell: re-run with --yes to confirm.", file=sys.stderr)
            return 1
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 0

    if src == "osm" and total > 150_000:
        print(
            "Note: large OSM bulk downloads burden tile.openstreetmap.org. "
            "Consider --max-zoom 17 or Geofabrik extracts for huge areas.\n",
            file=sys.stderr,
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    fail = 0
    skipped = 0
    t0 = time.time()
    for z in range(args.min_zoom, max_z + 1):
        xa, xb, ya, yb = tile_range_for_bbox(west, south, east, north, z)
        for x in range(xa, xb + 1):
            for y in range(ya, yb + 1):
                dest = out_dir / str(z) / str(x) / f"{y}.{ext}"
                if dest.exists() and dest.stat().st_size > 100:
                    skipped += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                url = tile_url(src, z, x, y)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        data = resp.read()
                    dest.write_bytes(data)
                    ok += 1
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        fail += 1
                    else:
                        print(f"HTTP {e.code} {url}", file=sys.stderr)
                        fail += 1
                except OSError as e:
                    print(f"{url}: {e}", file=sys.stderr)
                    fail += 1

                time.sleep(sleep)

    dt = time.time() - t0
    print(
        f"Done: {ok} downloaded, {skipped} already present, {fail} failed, {dt/60:.1f} min"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
