# Skydock mission log viewer (Flask)

## Run locally

No `PYTHONPATH` needed — `app.py` adds the repo root and this folder to `sys.path`.

From the **repository root**:

```bash
python tools/log_server/app.py
```

Or from this directory:

```bash
cd tools/log_server
python app.py
```

Opening **`/`** in the browser redirects to the **mission list** (`/missions`). Use **Compare** in the header to open side-by-side analysis.

If you use **gunicorn** or import the app without running `app.py`, set `PYTHONPATH` to the repo root and `tools/log_server` (or `cd tools/log_server` and include `../..`).

- **Port:** `PORT` (default `5000`).
- **Dev mode:** `FLASK_DEBUG=1` or `LOG_SERVER_DEBUG=1` enables Flask debug (reloader and exception pages). Omit in production.

## Mission index (SQLite sidecar)

For large logs, build a sidecar index next to each `mission.jsonl` (`mission_index.sqlite`). The log reader uses it automatically when the file revision matches.

Build or refresh manually (no `PYTHONPATH`; same path bootstrap as `app.py`):

```bash
python tools/log_server/index_mission.py --mission-id 0001
# or
python tools/log_server/index_mission.py /path/to/mission.jsonl --force
```

From the mission **log analysis** page you can also use **Build index** when the sidecar is missing.

Optional: set `SKYDOCK_AUTO_MISSION_INDEX=1` so the first read of a log without a valid index triggers a background-compatible rebuild (can add latency on first open).

## Production

Do not enable debug on a network-facing host. Use a WSGI server, for example from the repo root:

```bash
export PYTHONPATH="$PWD:$PWD/tools/log_server"
cd tools/log_server
gunicorn -w 2 -b 0.0.0.0:5000 "factory:create_app()"
```

(`PYTHONPATH` is required here because gunicorn imports `factory` without running `app.py`.)

## Tests

```bash
pytest tools/log_server/tests/
```
