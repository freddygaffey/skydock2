# Configuration

System config snapshots for the drone's PPP-over-RFD900 link. Captured 2026-05-10.

## Topology

```
Laptop (deb, 10.0.0.2) <-- USB --> RFD900 <-- 915 MHz --> RFD900 <-- UART --> RPi (rpi, 10.0.0.1)
       |                                                                              |
       +-- wifi (wlp8s0) -- internet                                                  |
            ^------------- NAT (nat-ppp.service) -- ppp0 ------------------------------+
```

Laptop shares wifi to RPi via PPP link so RPi has internet in the field through the operator's hotspot/wifi.

## Files

### `deb/` — laptop (Debian/Ubuntu)

| File | Install path |
|------|--------------|
| `ppp-peers-ubuntu-serial` | `/etc/ppp/peers/ubuntu-serial` |
| `ppp-serial.service` | `/etc/systemd/system/ppp-serial.service` |
| `nat-ppp.service` | `/etc/systemd/system/nat-ppp.service` |

USB device: CP2102 RFD900 dongle on `/dev/ttyUSB0`. (May rename if other USB-serial devices are present — see "Hardening" below.)

### `rpi/` — Raspberry Pi 5

| File | Install path |
|------|--------------|
| `ppp-peers-pi-serial` | `/etc/ppp/peers/pi-serial` |
| `ppp-serial.service` | `/etc/systemd/system/ppp-serial.service` |

UART: GPIO 14/15 → `/dev/serial0` → `/dev/ttyAMA0`. Requires `enable_uart=1` in `/boot/firmware/config.txt`.

## Install

```bash
# Laptop
sudo cp deb/ppp-peers-ubuntu-serial /etc/ppp/peers/ubuntu-serial
sudo cp deb/ppp-serial.service /etc/systemd/system/
sudo cp deb/nat-ppp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ppp-serial.service nat-ppp.service

# RPi
sudo cp rpi/ppp-peers-pi-serial /etc/ppp/peers/pi-serial
sudo cp rpi/ppp-serial.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ppp-serial.service
```

## Verify

```bash
ip -br addr show ppp0          # both sides should show 10.0.0.x peer 10.0.0.y
ping -c 3 10.0.0.1             # from laptop
ssh fred@rpi.local 'ping -I ppp0 -c 3 8.8.8.8'   # internet via NAT
```

## Notes / known issues

- **Duplicate units**: earlier setup created `ppp-ubuntu.service` (laptop) and `ppp-pi.service` (RPi) alongside the `ppp-serial.service` units. They competed for the same TTY and broke the link. The `ppp-serial.service` versions kept here are the survivors (better — they bind to the device unit and clean stale lock files).
- **USB rename risk**: laptop unit binds to `/dev/ttyUSB0` by name. If another USB-serial device is plugged in and the RFD re-enumerates as `ttyUSB1`, the link breaks. Fix: switch to `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` and update `BindsTo`/`WantedBy` to the matching escaped device unit name. Not applied here.
- Link is ~57600 baud over RFD900 — expect ~100ms RTT, occasional packet loss is normal.
