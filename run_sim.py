import sys
import subprocess

from sitl import get_sim_files, slot_port

speed = int(float(sys.argv[sys.argv.index("--speed") + 1])) if "--speed" in sys.argv else 1

sim_files = get_sim_files()
print(f"[run_sim] launching {len(sim_files)} vehicles: {sim_files}")

children = []
for slot, f in enumerate(sim_files):
    port = slot_port(slot)
    cmd = (
        f"{sys.executable} main.py --sim '{f}' --sim-port {port} --speed {speed}; "
        f"echo 'Done - press enter to close'; read"
    )
    child = subprocess.Popen(
        ["xterm", "-title", f"Vehicle {slot} - {f}", "-e", "bash", "-c", cmd]
    )
    children.append(child)

for c in children:
    c.wait()
