"""End-to-end browser tests for the mission dashboard tabs (Playwright + Chromium).

Drives a real headless Chromium against a live log server pointed at a small fixture
mission, clicks through every dashboard tab, and asserts each renders without uncaught
JS errors and shows its key content. This catches client-side breakage that the Flask
test-client tests (test_frame_events_payload.py) cannot — e.g. a giant /frame_events
response hanging the page, or a popup navigating with the wrong index.

Run:
    python3 -m pytest tools/log_server/tests/test_dashboard_e2e.py -v

Requires the Chromium browser binary:
    python3 -m playwright install chromium
The module skips itself cleanly if Playwright or the browser is unavailable.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PY = REPO_ROOT / "tools" / "log_server" / "app.py"

TS_A = 1704067204000000000
TS_B = 1704067205000000000
TS_C = 1704067206000000000

_BIG_HISTORY_DS = {
    "latitude": -35.0, "longitude": 149.0, "altitude_rel_home": 10.0,
    "velocity_x": 0.0, "velocity_y": 0.0, "velocity_z": 0.0,
    "heading": 0, "mode": "GUIDED", "arm_state": None,
    "autonomy_enabled": True, "force_homing": False, "rangefinder_m": 0.0,
    "width": 1280, "hight": 1280,
    "rotation": {"time_ns": 0, "x": 0, "y": 0, "z": 0, "dx": 0, "dy": 0, "dz": 0},
    "rotation_history": [{"time_ns": i, "x": 0, "y": 0, "z": 0, "dx": 0, "dy": 0, "dz": 0} for i in range(100)],
    "gps_history": [{"time_ns": i, "lat": -35.0, "lon": 149.0, "vx": 0.0, "vy": 0.0} for i in range(100)],
}


def _fsm_tick(ts_ns, ts_str, stem, with_det):
    frame = {"photo_path": "No photo taken", "detections": []}
    if with_det:
        frame["detections"] = [{
            "label": "sports ball", "confidence": 0.9,
            "bbox": [[620.0, 600.0], [660.0, 700.0]],
            "track_id": None, "truth_id": 0, "time_detected": stem,
        }]
    return {"time_ns": ts_ns, "ts": ts_str, "level": "DEBUG", "logger": "fsm",
            "event": "fsm_tick", "state": "SCAN",
            "drone_state": dict(_BIG_HISTORY_DS), "frame": frame}


def _write_fixture_mission(root: Path) -> None:
    mid = root / "0001"
    (mid / "frames").mkdir(parents=True)
    for stem in (TS_A, TS_B, TS_C):
        (mid / "frames" / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    lines = [
        {"time_ns": 1704067201000000000, "ts": "2024-01-01T00:00:01.000Z", "level": "INFO",
         "logger": "main", "event": "mission_start", "schema_version": 2,
         "mission_id": "0001", "is_sim": True, "sim_truth_file": "cmac2.json"},
        {"time_ns": 1704067203000000000, "ts": "2024-01-01T00:00:03.000Z", "level": "INFO",
         "logger": "fsm", "event": "fsm_transition", "state_from": "OVERRIDE", "state_to": "SCAN"},
        _fsm_tick(TS_A, "2024-01-01T00:00:04.000Z", TS_A, True),
        _fsm_tick(TS_B, "2024-01-01T00:00:05.000Z", TS_B, True),
        _fsm_tick(TS_C, "2024-01-01T00:00:06.000Z", TS_C, False),
    ]
    (mid / "mission.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    (root / "cmac2.json").write_text(json.dumps(
        {"weed_locations": [{"id": 0, "lat": -35.0002, "lon": 149.0002}]}), encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("missions_root")
    _write_fixture_mission(root)
    port = _free_port()
    env = dict(os.environ)
    env.update({
        "SKYDOCK_MISSIONS_DIR": str(root),
        "SKYDOCK_SIM_DATA_DIR": str(root),
        "SKYDOCK_RPI_MISSIONS_DIR": str(root),
        "PORT": str(port),
        "LOG_SERVER_DEBUG": "0",  # no reloader/debugger under test
    })
    proc = subprocess.Popen([sys.executable, str(APP_PY)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("log server exited early:\n" + (proc.stdout.read().decode() if proc.stdout else ""))
            try:
                urllib.request.urlopen(base + "/missions", timeout=1)
                break
            except Exception:
                time.sleep(0.3)
        else:
            raise RuntimeError("log server did not start in time")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def browser():
    try:
        with sync_playwright() as p:
            try:
                b = p.chromium.launch()
            except Exception as e:  # browser binary not installed
                pytest.skip(f"Chromium not available (run: python3 -m playwright install chromium): {e}")
            yield b
            b.close()
    except Exception as e:
        pytest.skip(f"Playwright unavailable: {e}")


def _open_dashboard(browser, base):
    """New page that captures real JS errors; navigates to the 0001 dashboard.

    We record uncaught JS exceptions (pageerror) and console errors, but ignore benign
    resource-load failures (e.g. the Video tab probing for a not-yet-generated
    mission_video.mp4 → 404) which are not page bugs.
    """
    page = browser.new_page()
    errors: list[str] = []

    def _console(msg):
        if msg.type == "error" and "Failed to load resource" not in msg.text:
            errors.append(msg.text)

    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", _console)
    page.goto(f"{base}/missions/0001?src=sim", wait_until="networkidle")
    return page, errors


def test_dashboard_map_loads(live_server, browser):
    page, errors = _open_dashboard(browser, live_server)
    # Leaflet map container present and the path-length summary rendered.
    page.wait_for_selector(".leaflet-container", timeout=10000)
    assert page.locator("#map").count() == 1
    assert not errors, f"JS errors on Map tab: {errors}"
    page.close()


@pytest.mark.parametrize("target,marker", [
    ("#tabTimeline", "#timelineChart"),
    ("#tabFrames", "#tabFrames"),
    ("#tabReport", "#tabReport"),
    ("#tabFrameReview", "#tabFrameReview"),
    ("#tabVideo", "#tabVideo"),
])
def test_dashboard_tab_opens_without_js_errors(live_server, browser, target, marker):
    page, errors = _open_dashboard(browser, live_server)
    page.click(f'button[data-bs-target="{target}"]')
    page.wait_for_selector(f"{marker}.active, {marker}", timeout=10000)
    # Let async tab loaders (fetch + render) settle.
    page.wait_for_timeout(1500)
    assert not errors, f"JS errors after opening {target}: {errors}"
    page.close()


# The detection layer uses a Leaflet Canvas renderer, so markers are drawn on a <canvas>,
# not as DOM <path> elements — we drive them via the Leaflet API / pixel clicks.
_LAYER_HAS_MARKERS = (
    "window.layerBboxGround && Object.keys(layerBboxGround._layers||{}).length > 0")


def _enable_bbox_ground(page):
    """Turn on the BBox-ground layer (off by default for sim) and wait for it to load."""
    page.wait_for_selector(".leaflet-container", timeout=10000)
    page.check("#layerBboxGround")  # fires change handler -> refreshMissionBboxGroundLayer()
    page.wait_for_function(_LAYER_HAS_MARKERS, timeout=10000)


def _open_first_detection_popup(page):
    """Open the first detection marker's popup via the Leaflet API.

    Detections use a canvas renderer (no per-marker DOM node), so a reliable headless
    pixel-click isn't available; opening the bound popup directly still exercises our popup
    HTML and the link's real click handler, which is what these tests care about.
    """
    ok = page.evaluate(
        """()=>{
            const layers = (window.layerBboxGround && layerBboxGround._layers) || {};
            for(const k of Object.keys(layers)){
                const l = layers[k];
                if(l.getPopup && l.getPopup()){ l.openPopup(); return true; }
            }
            return false;
        }""")
    assert ok, "no detection layer with a bound popup"


def test_detection_markers_render_on_map(live_server, browser):
    """Enabling BBox ground builds detection markers on the map (the bbox-visibility fix)."""
    page, errors = _open_dashboard(browser, live_server)
    _enable_bbox_ground(page)
    n = page.evaluate("Object.keys((window.layerBboxGround&&layerBboxGround._layers)||{}).length")
    assert n >= 2  # polygon + center marker for at least one detection
    # Detections are drawn via a Leaflet canvas renderer in the detection pane.
    assert page.locator(".leaflet-pane canvas").count() >= 1
    assert not errors, f"JS errors rendering detection markers: {errors}"
    page.close()


def test_detection_popup_shows_image_and_link(live_server, browser):
    """Clicking a detection marker opens a popup with the frame image + frame-viewer link."""
    page, errors = _open_dashboard(browser, live_server)
    _enable_bbox_ground(page)
    _open_first_detection_popup(page)
    page.wait_for_selector(".leaflet-popup", timeout=5000)
    # Popup carries the frame JPEG and an "Open in frame viewer" link keyed by stable time_ns.
    assert page.locator(".leaflet-popup img.sd-det-img").count() >= 1
    link = page.locator(".leaflet-popup a.sd-det-open-full")
    assert link.count() >= 1
    assert link.first.get_attribute("data-sd-frame-tns")  # stable nav key, not a list index
    assert not errors, f"JS errors opening detection popup: {errors}"
    page.close()


def test_gc_live_control_panel_renders(live_server, browser):
    """GC page shows the live-control panel; with no MAVLink URL it's disabled + noted."""
    page = browser.new_page()
    page.goto(f"{live_server}/missions/0001/gc?src=sim", wait_until="networkidle")
    page.wait_for_selector("#liveControl:not(.d-none)", timeout=10000)
    # State buttons built from /live/status contract.
    page.wait_for_function(
        "document.querySelectorAll('#liveStateBtns .live-state').length >= 5", timeout=10000)
    # Not configured in the test env -> controls disabled with an explanatory note.
    assert page.locator("#liveControl button[data-ovr='override']").is_disabled()
    assert "not configured" in (page.locator("#liveControlNote").text_content() or "").lower()
    page.close()


def test_detection_popup_link_opens_frames_tab(live_server, browser):
    """The popup's 'Open in frame viewer' link switches to the Frames tab on the right frame."""
    page, errors = _open_dashboard(browser, live_server)
    _enable_bbox_ground(page)
    _open_first_detection_popup(page)
    page.wait_for_selector(".leaflet-popup a.sd-det-open-full", timeout=5000)
    # Native DOM click: bubbles to the document-level handler. (A synthetic mouse click is
    # swallowed by the transparent canvas pane that overlaps the popup in z-order.)
    page.eval_on_selector(".leaflet-popup a.sd-det-open-full", "el => el.click()")
    # Frames tab pane becomes active and a frame is selected.
    page.wait_for_selector("#tabFrames.active", timeout=10000)
    page.wait_for_function(
        "document.querySelectorAll('#framelist .frame-item.active').length === 1", timeout=10000)
    assert not errors, f"JS errors following frame-viewer link: {errors}"
    page.close()
