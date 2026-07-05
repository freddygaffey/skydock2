"""E2E test for the live-frame viewer page (Playwright + Chromium).

Drives real headless Chromium against the server.py viewer and verifies the
fps controls: arrow-key bindings, number-box/slider sync, and clamping.
Skips cleanly if Playwright or the Chromium binary is unavailable.

Run: python3 -m pytest tests/test_server_e2e.py -v
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

playwright_api = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

import server  # noqa: E402


@pytest.fixture(scope="module")
def viewer():
    from werkzeug.serving import make_server

    app = server.create_app(fsm=None)
    srv = make_server("127.0.0.1", 0, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            srv.shutdown()
            pytest.skip("chromium not installed (python3 -m playwright install chromium)")
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_load_state()
        yield page, errors
        browser.close()
    srv.shutdown()


def _fps(page):
    return page.input_value("#fpsnum"), page.input_value("#fps")


def test_arrow_keys_change_fps_and_stay_synced(viewer):
    page, errors = viewer
    assert page.input_value("#fpsnum") == "5"

    page.keyboard.press("ArrowUp")
    assert _fps(page) == ("6", "6")

    page.keyboard.press("Shift+ArrowDown")
    assert _fps(page) == ("5.75", "5.75")

    page.keyboard.press("ArrowDown")
    assert _fps(page) == ("4.75", "4.75")

    assert errors == []


def test_arrow_keys_clamp_at_bounds(viewer):
    page, errors = viewer

    page.fill("#fpsnum", "0.5")
    page.keyboard.press("ArrowDown")   # 0.5 - 1 -> clamps to 0.25
    assert _fps(page) == ("0.25", "0.25")

    page.fill("#fpsnum", "29.5")
    page.keyboard.press("ArrowUp")     # 29.5 + 1 -> clamps to 30
    assert _fps(page) == ("30", "30")

    assert errors == []


def test_typing_in_number_box_moves_slider(viewer):
    page, errors = viewer
    page.fill("#fpsnum", "12")
    assert page.input_value("#fps") == "12"
    assert errors == []
