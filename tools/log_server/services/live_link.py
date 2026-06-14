"""Ground-side live control link to the drone over MAVLink (via MAVProxy).

The log server runs on the ground computer. To command a *live* drone it connects to a
MAVProxy / MAVLink endpoint (``SKYDOCK_MAVLINK_URL``) and sends:

  - RC channel overrides — the FSM state-register channel and the autonomy/override
    switch (chan16),
  - body-frame position nudges (``SET_POSITION_TARGET_LOCAL_NED``, magnitude clamped),
  - flight-mode changes (e.g. RTL).

CONTRACT (must match the flight-side reader — Part A in CLAUDE.md):
  The RC channel numbers and PWM bands defined here MUST equal what drone_state/fsm read
  on the Pi. They live here for now because this is the log-server-first slice; when the
  flight-side state register lands, move these into a shared constants module and import
  them in both places so they can never drift.

Everything degrades gracefully when no MAVLink URL is configured (the normal post-mission
log-viewer case): endpoints report ``configured: false`` and refuse to send.
"""

from __future__ import annotations

import threading
from typing import Optional

import config

# --- RC contract (mirror on the flight side) -----------------------------------------

# Spare channel carrying the requested/!current FSM state (chan16 is the autonomy switch).
STATE_RC_CHANNEL = 15
# PWM (µs) per GC-settable state. Centre of a ±60 band. RTL is reached via flight mode,
# DONE is terminal — neither is settable here.
STATE_PWM = {
    "OVERRIDE": 1100,
    "SCAN": 1250,
    "GOTO": 1400,
    "HOMING": 1550,
    "SPRAY": 1700,
}

# Existing autonomy/override switch (already read by drone_state on real hardware):
#   low → autonomy on, mid → override (FSM releases control), high → force homing.
OVERRIDE_RC_CHANNEL = 16
OVERRIDE_PWM = {
    "autonomy": 1000,
    "override": 1500,
    "force_homing": 2000,
}

# Safety clamp for a single nudge (metres).
NUDGE_MAX_M = 2.0

# Body-frame (x fwd, y right, z down) unit offsets for each nudge direction.
NUDGE_DIRS = {
    "forward": (1.0, 0.0, 0.0),
    "back": (-1.0, 0.0, 0.0),
    "left": (0.0, -1.0, 0.0),
    "right": (0.0, 1.0, 0.0),
    "up": (0.0, 0.0, -1.0),
    "down": (0.0, 0.0, 1.0),
}

# SET_POSITION_TARGET type_mask: use position x/y/z, ignore vel/accel/yaw (matches the
# flight code's position-only bitmask).
_POS_ONLY_TYPE_MASK = 0b0000_1111_1111_1000  # 3576
_RC_IGNORE = 65535  # leave a channel untouched in RC_CHANNELS_OVERRIDE


class LiveLinkError(RuntimeError):
    pass


class LiveLink:
    """Lazily-connected MAVLink sender. Thread-safe; safe to import without pymavlink."""

    def __init__(self) -> None:
        self._conn = None
        self._lock = threading.Lock()

    # -- connection ---------------------------------------------------------------------

    def configured(self) -> bool:
        return bool(config.mavlink_url())

    def _ensure_conn(self):
        if not self.configured():
            raise LiveLinkError("live control not configured (set SKYDOCK_MAVLINK_URL)")
        if self._conn is None:
            try:
                from pymavlink import mavutil  # imported lazily — optional dependency
            except Exception as e:  # pragma: no cover - env-dependent
                raise LiveLinkError(f"pymavlink not available: {e}")
            conn = mavutil.mavlink_connection(config.mavlink_url())
            self._conn = conn
        return self._conn

    def status(self) -> dict:
        return {
            "configured": self.configured(),
            "connected": self._conn is not None,
            "url": config.mavlink_url(),
            "state_channel": STATE_RC_CHANNEL,
            "override_channel": OVERRIDE_RC_CHANNEL,
            "nudge_max_m": NUDGE_MAX_M,
            "states": sorted(STATE_PWM),
        }

    def _targets(self):
        c = self._conn
        return (getattr(c, "target_system", 0) or 1, getattr(c, "target_component", 0) or 1)

    # -- commands -----------------------------------------------------------------------

    def set_rc(self, channel: int, pwm: int) -> None:
        """Override a single RC channel (others left untouched)."""
        if not (1 <= channel <= 18):
            raise LiveLinkError(f"rc channel out of range: {channel}")
        with self._lock:
            conn = self._ensure_conn()
            sysid, compid = self._targets()
            chans = [_RC_IGNORE] * 18
            chans[channel - 1] = int(pwm)
            conn.mav.rc_channels_override_send(sysid, compid, *chans)

    def set_state(self, state: str) -> int:
        state = str(state).upper()
        if state not in STATE_PWM:
            raise LiveLinkError(f"unknown/!settable state: {state} (choices: {sorted(STATE_PWM)})")
        pwm = STATE_PWM[state]
        self.set_rc(STATE_RC_CHANNEL, pwm)
        return pwm

    def set_override(self, mode: str) -> int:
        mode = str(mode).lower()
        if mode not in OVERRIDE_PWM:
            raise LiveLinkError(f"unknown override mode: {mode} (choices: {sorted(OVERRIDE_PWM)})")
        pwm = OVERRIDE_PWM[mode]
        self.set_rc(OVERRIDE_RC_CHANNEL, pwm)
        return pwm

    def nudge(self, direction: str, meters: float) -> tuple[float, float, float]:
        direction = str(direction).lower()
        if direction not in NUDGE_DIRS:
            raise LiveLinkError(f"unknown direction: {direction} (choices: {sorted(NUDGE_DIRS)})")
        try:
            meters = float(meters)
        except (TypeError, ValueError):
            raise LiveLinkError("meters must be a number")
        # Clamp magnitude for safety.
        meters = max(0.0, min(NUDGE_MAX_M, abs(meters)))
        ux, uy, uz = NUDGE_DIRS[direction]
        dx, dy, dz = ux * meters, uy * meters, uz * meters
        with self._lock:
            conn = self._ensure_conn()
            sysid, compid = self._targets()
            try:
                from pymavlink import mavutil
                frame = mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED
            except Exception:
                frame = 8  # MAV_FRAME_BODY_OFFSET_NED
            conn.mav.set_position_target_local_ned_send(
                0, sysid, compid, frame, _POS_ONLY_TYPE_MASK,
                dx, dy, dz, 0, 0, 0, 0, 0, 0, 0, 0,
            )
        return (dx, dy, dz)

    def set_mode(self, mode: str) -> str:
        mode = str(mode).upper()
        with self._lock:
            conn = self._ensure_conn()
            try:
                conn.set_mode(mode)
            except Exception as e:
                raise LiveLinkError(f"set_mode({mode}) failed: {e}")
        return mode


# Module singleton used by the routes.
live_link = LiveLink()
