"""Skydock mission log viewer (Flask). Run: python app.py from this directory, or python tools/log_server/app.py from repo root."""

from __future__ import annotations

import os

from factory import create_app

app = create_app()


if __name__ == "__main__":
    from config import data_paths

    port = int(os.environ.get("PORT", "5000"))
    _sim, missions_root = data_paths()
    missions = sorted(missions_root.glob("*/mission.jsonl")) if missions_root.exists() else []
    print(f"\n  MISSIONS_ROOT : {missions_root}  ({'exists' if missions_root.exists() else 'MISSING'})")
    print(f"  SIM_DATA_ROOT : {_sim}  ({'exists' if _sim.exists() else 'missing'})")
    if missions:
        print("  Mission files :")
        for m in missions:
            size_kb = m.stat().st_size // 1024
            print(f"    {m}  ({size_kb} KB)")
    else:
        print("  Mission files : (none found)")
    print()
    # threaded=True: parallel API requests (map + summary + frame_events) on first dashboard load
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)
