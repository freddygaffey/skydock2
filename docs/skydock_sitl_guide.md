## Running skydock2 in ArduPilot SITL

This guide explains how to run the `skydock2` controller against an ArduPilot SITL instance on Linux.  
It assumes you have already installed ArduPilot and can run `sim_vehicle.py` (see `setting_up_sitl.md` for a full SITL + Gazebo setup guide).

---

### 1. Install Python dependencies

From the repo root (`/home/fred/skydock2`):

```bash
cd /home/fred/skydock2

# (optional but recommended)
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies (from `requirements.txt`):

- **numpy**
- **opencv-python**
- **pymavlink**
- **pyserial**
- **sqlalchemy**

---

### 2. Start ArduPilot SITL and expose UDP 14552

`telemetry.py` first tries to connect using `udp:127.0.0.1:14552`, so your SITL must stream MAVLink to that port.

In a new terminal, you can use the exact command you already run:

```bash
cd ~/ardupilot/ArduCopter

sim_vehicle.py -v ArduCopter -w --console --map \
  --out=tcp:127.0.0.1:5760 \
  --out=udp:127.0.0.1:14552
```

Notes:

- The important part for `skydock2` is `--out=udp:127.0.0.1:14552` – this matches the first entry in `connection_palths` in `telemetry.py`, so no code changes are needed.
- The extra TCP output (`--out=tcp:127.0.0.1:5760`) is fine and can be used by a GCS/MAVProxy.
- Wait until SITL has fully booted and is sending heartbeats before starting `skydock2`.

If you ever change the UDP port, you must:

1. Change the corresponding entry in `connection_palths` in `telemetry.py`, **or**
2. Add a second `--out` in `sim_vehicle.py` that matches `udp:127.0.0.1:14552`.

---

### 3. (Optional) Load an AUTO mission in SITL

If you want to use the “new mission from currently saved auto mission” option in `main.py`, you should have a mission already stored on the vehicle:

1. Connect Mission Planner, QGroundControl, or MAVProxy to SITL.
2. Create and upload an **AUTO** mission.
3. Keep SITL running with that mission loaded.

You can skip this step if you only want to test basic behavior.

---

### 4. Run `skydock2` in SIM mode

In another terminal:

```bash
cd /home/fred/skydock2
source .venv/bin/activate  # if you created the venv

python3 main.py -s
```

The `-s` / `--sim` flag puts `main.py` into simulation mode:

- It uses synthetic camera detections from `sim_ai.py` instead of a real camera.
- It loads weed locations and scan paths from JSON files in `sim_data/`.
- It runs the state machine (`fsm.StateMachine`) against live telemetry from SITL.

You will see:

```text
sim mode
sim file:
```

At the `sim file:` prompt:

- Press **Enter** to run all `.json` files in `sim_data/`, **or**
- Type a specific file name (with or without `.json`).

Each JSON file should define:

- `weed_locations`: list of `[lat, lon]` pairs.
- `scan_path`: list of waypoints, which are converted into `Waypoint` objects and loaded into the DB.

---

### 5. Menu options (r / n / c / w)

After processing sim data, `main.py` prints:

```text
you are about to fly do your prflight checks
press r to resume
press n for a new mission from the currently saved auto mission
press c to cancel and ctrl + c should also stop it at any time mabey
w just uplod a weed location this is where home is

press r/n/c/w
```

Meaning:

- **`n` (new mission)**  
  - Downloads the current AUTO mission from the FC via `telemetry_singlton.get_auto_mission_wp()`.
  - Converts it into `Waypoint` objects and stores them in the DB (replacing existing waypoints).

- **`r` (resume)**  
  - Uses the mission already stored in the DB (no changes).

- **`w` (mark weed/home)**  
  - Takes the current drone GPS position from `telemetry_singlton.drone_state`.
  - Stores it as a single `Waypoint` (weed/home location).

- **`c` (cancel)**  
  - Exits `main.py`.

Pick the option that matches what you want to test.

---

### 6. Coordinate takeoff with SITL

After the menu, `main.py` asks:

```text
type y when taken off (y)
```

This script does **not** perform the actual takeoff. You must:

1. In your GCS / MAVProxy connected to SITL:

   ```bash
   mode guided
   arm throttle
   takeoff 5
   ```

2. Once the simulated drone is in the air (e.g. ~5 m AGL), go back to the `main.py` terminal and type:

   ```text
   y
   ```

`main.py` then:

- Calls `ai_storage_singleton.start_ai()` (or continues the sim AI).
- Creates `fsm.StateMachine()`.
- Enters the main update loop.

---

### 7. How the FSM and telemetry interact in SITL

Key components:

- **`telemetry.Telemetry`**
  - Connects to SITL via `pymavlink.mavutil.mavlink_connection`.
  - Tries several `connection_palths`, starting with `udp:127.0.0.1:14552`.
  - Populates a `DroneStateForHoming` instance (`telemetry_singlton.drone_state`).

- **`drone_state.DroneStateForHoming`**
  - Tracks:
    - GPS position and relative altitude (`GLOBAL_POSITION_INT`).
    - Velocity.
    - Mode and arm state (`HEARTBEAT`).
    - A flag `enable_homing_and_autonomy`.
  - In SIM mode (`-s`), `enable_homing_and_autonomy` is set to `True` whenever a `SERVO_OUTPUT_RAW` message is seen.

- **`sim_ai.run_sim_ai`**
  - Background thread at 30 FPS.
  - Uses current `drone_state` and `weed_locations` from the sim JSON.
  - Computes which weeds are visible in the “camera”.
  - Writes a `Frame` with `Detection`s to `ai_storage_singleton`.

- **`fsm.StateMachine`**
  - Reads:
    - `drone_state` from `telemetry_singlton`.
    - `frame` from `ai_storage_singleton.get_latest_frame()`.
  - Manages states (`OVERRIDE`, `SCAN`, `GOTO`, `HOMING`, `SPRAY`, `RTL`, `DONE`).
  - Uses `_overide_and_rtl_checks` to:
    - Force `RTL` state if the FC mode is `RTL`.
    - Force `OVERRIDE` if mode is anything other than `GUIDED`.
    - Force `OVERRIDE` (and stop velocity commands) if `enable_homing_and_autonomy` is `False`.
    - Transition into `SCAN` when entering GUIDED from OVERRIDE or RTL.

For SITL to actually run autonomous behavior:

- Vehicle **mode must be `GUIDED`**.
- In SIM mode (`-s` flag), `enable_homing_and_autonomy` is automatically set to `True` once servo data starts arriving.

If you see the FSM stuck in `OVERRIDE`:

1. Check the SITL mode (it should be `GUIDED`).
2. Make sure `main.py` was started with `-s` / `--sim`.
3. Ensure SITL is sending SERVO and GLOBAL_POSITION_INT messages (vehicle armed and running).

---

### 8. Minimal quick-start checklist

1. **Terminal 1 – Start SITL**

   ```bash
   cd ~/ardupilot/ArduCopter
   sim_vehicle.py -v ArduCopter -w --console --map \
     --out=tcp:127.0.0.1:5760 \
     --out=udp:127.0.0.1:14552
   ```

2. **Terminal 2 – Run `skydock2`**

   ```bash
   cd /home/fred/skydock2
   source .venv/bin/activate      # if created
   python3 main.py -s
   ```

3. **When prompted:**

   - Choose a sim file (or press Enter to use all in `sim_data/`).
   - Press `r` or `n` as desired.
   - In your GCS / MAVProxy, set `mode guided`, `arm`, and `takeoff`.
   - Type `y` in the `main.py` terminal once the drone is airborne.

After that, the finite state machine should begin driving behavior using SITL telemetry plus simulated AI detections.

