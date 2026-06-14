"""Tests for the ground-side live drone control endpoints (/live/*).

These exercise the log-server side only (the MAVLink sender + routes). A fake pymavlink
connection captures what would be sent, so nothing touches a real drone. The flight-side
reader (FSM state register) is a separate change and is NOT under test here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from factory import create_app
from services import live_link as ll


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def fake_conn(monkeypatch):
    """Configure a live link backed by a fake MAVLink connection (no real I/O)."""
    monkeypatch.setenv("SKYDOCK_MAVLINK_URL", "udpout:127.0.0.1:14550")
    conn = MagicMock()
    conn.target_system = 1
    conn.target_component = 1
    ll.live_link._conn = conn
    yield conn
    ll.live_link._conn = None


# --- not configured (normal log-viewer case) -----------------------------------------

def test_status_reports_not_configured(client, monkeypatch):
    monkeypatch.delenv("SKYDOCK_MAVLINK_URL", raising=False)
    ll.live_link._conn = None
    st = client.get("/live/status").get_json()
    assert st["configured"] is False
    assert st["state_channel"] == ll.STATE_RC_CHANNEL
    assert "OVERRIDE" in st["states"]


@pytest.mark.parametrize("path,payload", [
    ("/live/state", {"state": "SCAN"}),
    ("/live/override", {"mode": "override"}),
    ("/live/nudge", {"dir": "forward", "meters": 1}),
    ("/live/mode", {"mode": "RTL"}),
])
def test_endpoints_503_when_not_configured(client, monkeypatch, path, payload):
    monkeypatch.delenv("SKYDOCK_MAVLINK_URL", raising=False)
    ll.live_link._conn = None
    r = client.post(path, json=payload)
    assert r.status_code == 503
    assert r.get_json()["ok"] is False


# --- configured: commands reach MAVLink ----------------------------------------------

def test_set_state_sends_rc_override_on_state_channel(client, fake_conn):
    r = client.post("/live/state", json={"state": "homing"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    args = fake_conn.mav.rc_channels_override_send.call_args.args
    # args: sysid, compid, ch1..ch18  -> state channel carries HOMING's pwm, others ignored.
    chans = args[2:]
    assert chans[ll.STATE_RC_CHANNEL - 1] == ll.STATE_PWM["HOMING"]
    assert chans[0] == 65535  # untouched channel left ignored


def test_override_sets_chan16(client, fake_conn):
    r = client.post("/live/override", json={"mode": "force_homing"})
    assert r.status_code == 200
    chans = fake_conn.mav.rc_channels_override_send.call_args.args[2:]
    assert chans[ll.OVERRIDE_RC_CHANNEL - 1] == ll.OVERRIDE_PWM["force_homing"]


def test_nudge_clamps_magnitude_and_sets_position_target(client, fake_conn):
    r = client.post("/live/nudge", json={"dir": "forward", "meters": 999})
    assert r.status_code == 200
    off = r.get_json()["offset_m"]
    assert off == [ll.NUDGE_MAX_M, 0.0, 0.0]  # clamped to the safety max, body-forward
    assert fake_conn.mav.set_position_target_local_ned_send.called


def test_nudge_directions_map_to_body_axes(client, fake_conn):
    client.post("/live/nudge", json={"dir": "right", "meters": 1})
    assert client.post("/live/nudge", json={"dir": "down", "meters": 1}).get_json()["offset_m"] == [0.0, 0.0, 1.0]


def test_set_mode_calls_mavlink_set_mode(client, fake_conn):
    r = client.post("/live/mode", json={"mode": "rtl"})
    assert r.status_code == 200 and r.get_json()["mode"] == "RTL"
    fake_conn.set_mode.assert_called_once_with("RTL")


# --- validation ----------------------------------------------------------------------

@pytest.mark.parametrize("path,payload", [
    ("/live/state", {"state": "FLYING"}),     # not a real/settable state
    ("/live/override", {"mode": "nope"}),
    ("/live/nudge", {"dir": "sideways", "meters": 1}),
])
def test_bad_args_return_400(client, fake_conn, path, payload):
    r = client.post(path, json=payload)
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
