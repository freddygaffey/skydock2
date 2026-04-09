---

# PPP Serial Link Setup Between Raspberry Pi and Ubuntu (with MAVLink Option)

## **Objective**

Create a direct serial link between a Raspberry Pi and an Ubuntu laptop using PPP (Point-to-Point Protocol) and optionally enable MAVLink telemetry over the same radios.

---

## **1. Hardware Setup**

* Connect the two devices using a serial link (USB-to-serial adapter or Pi’s GPIO UART pins).
* Radios must have the **same NET ID** and matched frequency/channel settings.
* Use `minicom` to verify basic connectivity and see LED status: solid green = powered, flickering red = data transmission.

---

## **2. Verify Serial Communication**

* **On Pi:**

```bash
sudo minicom -D /dev/serial0 -b 57600
```

* **On Ubuntu:**

```bash
sudo minicom -D /dev/ttyUSB0 -b 57600
```

* Send test text between devices to verify that the serial link works.

---

## **3. Radio Configuration (Optional MAVLink)**

* Query radio parameters with:

```text
ATI5
```

* Relevant settings:

  * `S6:MAVLINK=0` → MAVLink disabled (use for transparent PPP link)
  * `S6:MAVLINK=1` → MAVLink enabled (for autopilot telemetry)

> **Note:** If MAVLink is enabled, the serial line will carry MAVLink messages, which may interfere with PPP. Disable MAVLink for a pure PPP/SSH link.

* Example command to disable MAVLink:

```text
ATS6=0
AT&W      # Save settings
```

---

## **4. Install PPP**

```bash
sudo apt update
sudo apt install ppp
```

---

## **5. Configure PPP Peers**

### **Pi: `/etc/ppp/peers/pi-serial`**

```text
/dev/serial0
57600
local
noauth
nocrtscts
debug
nodetach
10.0.0.1:10.0.0.2
```

### **Ubuntu: `/etc/ppp/peers/ubuntu-serial`**

```text
/dev/ttyUSB0
57600
local
noauth
nocrtscts
debug
nodetach
10.0.0.2:10.0.0.1
```

---

## **6. Start PPP Manually**

* **Pi:**

```bash
sudo pppd call pi-serial
```

* **Ubuntu:**

```bash
sudo pppd call ubuntu-serial
```

* Debug output shows LCP/IPCP negotiation.

---

## **7. Verify PPP Connection**

```bash
ip addr show ppp0
ping 10.0.0.2  # From Pi
ping 10.0.0.1  # From Ubuntu
```

---

## **8. SSH Over PPP**

```bash
ssh pi@10.0.0.1   # From Ubuntu
ssh fred@10.0.0.2 # From Pi
```

* Optional: enable passwordless SSH with key exchange:

```bash
ssh-keygen -t ed25519
ssh-copy-id pi@10.0.0.1
ssh-copy-id fred@10.0.0.2
```

---

## **9. Notes**

* Use `debug` in PPP to troubleshoot link setup.
* Ensure baud rates match (`57600` in this setup).
* MAVLink **must be disabled** for transparent PPP; enable it only if you want telemetry data.
* You can test radios first with `cat` or `minicom` before starting PPP.
* Automatic PPP can be set up with `systemd` service files.

---

