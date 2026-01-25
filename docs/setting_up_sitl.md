I have actually done this and it works
# Gazebo Harmonic + ArduPilot SITL Setup Guide

Complete installation guide for setting up Gazebo Harmonic simulation environment with ArduPilot SITL on Ubuntu 24.04 LTS.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1: Install Gazebo Harmonic](#step-1-install-gazebo-harmonic)
- [Step 2: Set Up ArduPilot Development Environment](#step-2-set-up-ardupilot-development-environment)
- [Step 3: Build ArduPilot SITL](#step-3-build-ardupilot-sitl)
- [Step 4: Install ardupilot_gazebo Plugin](#step-4-install-ardupilot_gazebo-plugin)
- [Step 5: Configure Environment Variables](#step-5-configure-environment-variables)
- [Step 6: Test the Integration](#step-6-test-the-integration)
- [Step 7: Basic Flight Commands](#step-7-basic-flight-commands)
- [Camera Controls](#camera-controls)
- [Troubleshooting](#troubleshooting)
- [Next Steps](#next-steps)

---

## Prerequisites

- **OS**: Ubuntu 24.04 LTS (Noble) x86_64
- **RAM**: Minimum 8 GB recommended
- **Disk Space**: ~5 GB for full installation
- **Internet Connection**: Required for package downloads
- **Sudo Privileges**: Required for system package installation

---

## Step 1: Install Gazebo Harmonic

### 1.1 Update System

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

### 1.2 Install Prerequisites

```bash
sudo apt-get install lsb-release wget gnupg -y
```

### 1.3 Add Gazebo Package Repository

```bash
sudo curl https://packages.osrfoundation.org/gazebo.gpg --output /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/gazebo-stable.list > /dev/null
```

### 1.4 Install Gazebo Harmonic

```bash
sudo apt-get update
sudo apt-get install gz-harmonic -y
```

### 1.5 Verify Installation

```bash
gz sim -v4 -r shapes.sdf
```

**Expected Result**: Gazebo window opens showing various 3D shapes. Close the window after verification.

---

## Step 2: Set Up ArduPilot Development Environment

### 2.1 Clone ArduPilot Repository

```bash
cd ~
git clone https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
```

### 2.2 Run Installation Script

```bash
Tools/environment_install/install-prereqs-ubuntu.sh -y
```

**Note**: This script will:
- Install required system packages
- Create a Python virtual environment at `~/venv-ardupilot`
- Set up necessary tools (MAVProxy, etc.)
- Update your `.bashrc` with required PATH variables

### 2.3 Reload Environment

```bash
source ~/.bashrc
```

---

## Step 3: Build ArduPilot SITL

### 3.1 Activate Virtual Environment

```bash
source ~/venv-ardupilot/bin/activate
```

Your prompt should now show `(venv-ardupilot)` prefix.

### 3.2 Install Python Dependencies

```bash
pip install empy==3.3.4
```

### 3.3 Configure and Build

```bash
cd ~/ardupilot
./waf configure --board sitl
./waf copter
```

**Expected Result**: Build completes successfully with message:
```
'copter' finished successfully (X.XXXs)
```

---

## Step 4: Install ardupilot_gazebo Plugin

### 4.1 Install Gazebo Development Dependencies

```bash
sudo apt update
sudo apt install libgz-sim8-dev rapidjson-dev -y
sudo apt install libopencv-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl -y
```

### 4.2 Create Workspace and Clone Plugin

```bash
mkdir -p ~/gz_ws/src
cd ~/gz_ws/src
git clone https://github.com/ArduPilot/ardupilot_gazebo.git
```

### 4.3 Build the Plugin

```bash
cd ardupilot_gazebo
mkdir build && cd build

# Set Gazebo version
export GZ_VERSION=harmonic

# Build
cmake .. -DCMAKE_BUILD_TYPE=RelWithDebInfo
make -j4
```

**Expected Result**: Build completes without errors.

---

## Step 5: Configure Environment Variables

### 5.1 Add to ~/.bashrc

```bash
cat >> ~/.bashrc << 'EOF'

# Gazebo Harmonic + ArduPilot SITL Configuration
export GZ_VERSION=harmonic
export GZ_SIM_SYSTEM_PLUGIN_PATH=$HOME/gz_ws/src/ardupilot_gazebo/build:${GZ_SIM_SYSTEM_PLUGIN_PATH}
export GZ_SIM_RESOURCE_PATH=$HOME/gz_ws/src/ardupilot_gazebo/models:$HOME/gz_ws/src/ardupilot_gazebo/worlds:${GZ_SIM_RESOURCE_PATH}

# Auto-activate ArduPilot virtual environment
source ~/venv-ardupilot/bin/activate
EOF
```

### 5.2 Reload Configuration

```bash
source ~/.bashrc
```

---

## Step 6: Test the Integration

### 6.1 Terminal 1: Launch Gazebo Simulation

```bash
cd ~/gz_ws/src/ardupilot_gazebo
gz sim -v4 -r iris_runway.sdf
```

**Wait** for Gazebo to fully load (you should see the Iris quadcopter on a runway).

### 6.2 Terminal 2: Start ArduPilot SITL

Open a **new terminal** and run:

```bash
cd ~/ardupilot
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --map --console
```

**Alternative** (if command not found):
```bash
cd ~/ardupilot
./Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --map --console
```

**Expected Result**: 
- MAVProxy console opens
- Connection established to simulated drone
- Prompt shows: `STABILIZE>`

---

## Step 7: Basic Flight Commands

In the MAVProxy console (Terminal 2), execute these commands:

### 7.1 Arm and Takeoff

```bash
STABILIZE> mode guided
GUIDED> arm throttle
GUIDED> takeoff 5
```

**Result**: Drone arms and takes off to 5 meters altitude in Gazebo.

### 7.2 Navigate to Position

```bash
GUIDED> wp set 1
# Enter coordinates when prompted
```

### 7.3 Land

```bash
GUIDED> mode land
```

### 7.4 Return to Launch

```bash
GUIDED> mode rtl
```

---

## Camera Controls

### Follow Mode (Easiest)

1. **Right-click** on the Iris drone in Gazebo 3D view
2. Select **"Follow"**
3. Camera now tracks the drone automatically

### Manual Camera Controls

- **Left-click + drag**: Rotate view
- **Middle-click + drag** (or Shift + left-click): Pan camera
- **Right-click + drag**: Zoom in/out
- **Scroll wheel**: Quick zoom
- **Ctrl + R**: Reset view

### Lost the Drone?

- Right-click in empty space → **"Move To"** → Select "iris"
- Or press **Ctrl + R** to reset camera

---

## Troubleshooting

### Issue: `sim_vehicle.py: command not found`

**Solution**:
```bash
# Reload bashrc
source ~/.bashrc

# Or use full path
cd ~/ardupilot
./Tools/autotest/sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --console
```

### Issue: `No module named pip`

**Solution**: Activate the virtual environment first:
```bash
source ~/venv-ardupilot/bin/activate
pip install empy==3.3.4
```

### Issue: Gazebo closes immediately

**Solution**: Check for errors:
```bash
gz sim -v4 -r iris_runway.sdf
```

Verify environment variables:
```bash
echo $GZ_SIM_SYSTEM_PLUGIN_PATH
echo $GZ_SIM_RESOURCE_PATH
```

### Issue: SITL can't connect to Gazebo

**Checklist**:
1. Gazebo fully loaded before starting SITL?
2. Run from `~/ardupilot` directory?
3. Check for firewall blocking localhost connections

**Debug Mode**:
```bash
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --console -D
```

### Issue: Build errors with `libgz-sim8-dev`

**Solution**: Ensure you installed Gazebo **Harmonic**, not Ionic:
```bash
# Check installed version
gz sim --version

# Should show: Gazebo Sim, version 8.x.x (Harmonic)
```

### Issue: Python package conflicts

**Solution**: Use the ArduPilot virtual environment:
```bash
source ~/venv-ardupilot/bin/activate
# Install all packages within this venv
```

---

## Next Steps

### Connecting Your Python Code

Your existing telemetry code can connect to SITL using:

```python
# Modify connection paths in telemetry.py
connection_paths = [
    "tcp:127.0.0.1:5762",  # SITL default
    "udp:127.0.0.1:14550", # Alternative SITL
    "/dev/ttyACM1",        # Physical hardware
    "/dev/ttyACM0"
]
```

### Adding Camera Simulation

The ardupilot_gazebo models support GStreamer camera plugins for computer vision testing:

```xml
<plugin name="GstCameraPlugin" filename="GstCameraPlugin">
    <udp_host>127.0.0.1</udp_host>
    <udp_port>5600</udp_port>
</plugin>
```

### Testing Autonomous Flight

1. Create waypoint missions
2. Test state machine logic in simulation
3. Validate computer vision algorithms with simulated camera

### Running Headless (No GUI)

For faster simulation when you don't need visualization:

```bash
# Gazebo headless
gz sim -s -r iris_runway.sdf

# SITL in separate terminal
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --console
```

---

## Useful Commands Reference

### Gazebo Commands

```bash
# List available worlds
ls ~/gz_ws/src/ardupilot_gazebo/worlds/

# Run different models
gz sim -v4 -r runway.sdf
gz sim -v4 -r iris_maze.sdf
```

### SITL Commands

```bash
# ArduCopter
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --console

# ArduPlane
sim_vehicle.py -v ArduPlane -f gazebo-zephyr --model JSON --console

# ArduRover
sim_vehicle.py -v Rover -f gazebo-rover --model JSON --console
```

### MAVProxy Commands

```bash
# Mode changes
mode guided
mode loiter
mode rtl
mode land

# Arming
arm throttle
disarm

# Movement
takeoff 10
wp set 1
goto 50 50 10

# Parameters
param show
param set PARAM_NAME value

# Status
status
```

---

## Additional Resources

- **ArduPilot SITL Documentation**: https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html
- **Gazebo Documentation**: https://gazebosim.org/docs/harmonic
- **ardupilot_gazebo GitHub**: https://github.com/ArduPilot/ardupilot_gazebo
- **MAVProxy Documentation**: https://ardupilot.org/mavproxy/

---

## System Requirements Summary

| Component | Requirement |
|-----------|-------------|
| OS | Ubuntu 24.04 LTS (Noble) |
| Gazebo | Harmonic (version 8.x) |
| ArduPilot | Latest master branch |
| Python | 3.8+ (system has 3.12.3) |
| RAM | 8 GB minimum |
| Disk Space | ~5 GB |

---

**Last Updated**: January 2026  
**Tested On**: Ubuntu 24.04.3 LTS x86_64