# AFERIY P280 Dashboard Telemetry

The dashboard can display AFERIY P280 telemetry as a power device.

Use local Bluetooth first. It talks directly to the power station and does not
need the P280 to stay connected to Wi-Fi. BrightEMS local MQTT is still
supported as an alternative if Bluetooth is not reliable in your install.

Until live telemetry is configured, the dashboard uses static fallback values.

## Install Bluetooth Support

Install the updated Python dependencies:

```bash
. .venv/bin/activate
python -m pip install -r requirements-pi.txt
```

On Raspberry Pi OS, make sure Bluetooth is enabled:

```bash
sudo systemctl enable --now bluetooth
bluetoothctl scan le
```

The power station usually advertises with a name starting with `POWER` or
`FOSSIBOT`. Some compatible units may use `AFERIY` or `SYDPOWER`.

## Dashboard Bluetooth Configuration

Set these values in `.env`:

```dotenv
DASHBOARD_AFERIY_ENABLED=true
DASHBOARD_AFERIY_SOURCE=ble
DASHBOARD_AFERIY_LABEL=AFERIY P280
DASHBOARD_AFERIY_MODEL=P280
DASHBOARD_AFERIY_CAPACITY_WH=2048

# Optional but recommended once you know the Bluetooth address.
DASHBOARD_AFERIY_BLE_ADDRESS=
DASHBOARD_AFERIY_BLE_NAME_PREFIXES=POWER,FOSSIBOT,AFERIY,SYDPOWER
DASHBOARD_AFERIY_BLE_SCAN_SECONDS=10
DASHBOARD_AFERIY_BLE_POLL_SECONDS=5
DASHBOARD_AFERIY_BLE_TIMEOUT_S=20
DASHBOARD_AFERIY_TELEMETRY_TTL_S=30
```

If `DASHBOARD_AFERIY_BLE_ADDRESS` is blank, the dashboard scans for the first
matching device name. After a successful connection, the Settings page shows the
Bluetooth address and RSSI so you can pin that address in `.env`.

Restart the dashboard after editing `.env`.

## Bluetooth Protocol

The dashboard connects to the BrightEMS-compatible BLE GATT service and polls
read-only Modbus-style registers:

```text
Service: 0000a002-0000-1000-8000-00805f9b34fb
Write:   0000c304-0000-1000-8000-00805f9b34fb
Notify:  0000c305-0000-1000-8000-00805f9b34fb
```

It only reads telemetry. It does not write output-control commands to the power
station.

## MQTT Alternative

If Bluetooth range or host Bluetooth support is poor, you can still use
BrightEMS/SYDPOWER local MQTT:

1. Run an MQTT broker on the dashboard Raspberry Pi.
2. In the BrightEMS app, point local MQTT at the Pi.
3. Set the dashboard `.env` values to read that broker.

Install Mosquitto on the Pi:

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

For a private motorhome LAN, a simple local listener is enough:

```bash
sudo tee /etc/mosquitto/conf.d/dashboard-local.conf >/dev/null <<'EOF'
listener 1883 0.0.0.0
allow_anonymous true
EOF
sudo systemctl restart mosquitto
```

Do not expose this broker to the public internet.

In the BrightEMS app, open the local MQTT broker settings and enter:

```text
Broker host: <dashboard-pi-ip>
Broker port: 1883
Username: blank, unless you configured one in Mosquitto
Password: blank, unless you configured one in Mosquitto
```

Then set these values in `.env`:

```dotenv
DASHBOARD_AFERIY_ENABLED=true
DASHBOARD_AFERIY_SOURCE=mqtt
DASHBOARD_AFERIY_LABEL=AFERIY P280
DASHBOARD_AFERIY_MODEL=P280
DASHBOARD_AFERIY_CAPACITY_WH=2048
DASHBOARD_AFERIY_MQTT_HOST=127.0.0.1
DASHBOARD_AFERIY_MQTT_PORT=1883
DASHBOARD_AFERIY_MQTT_DEVICE_ID=98:88:E0:52:22:F2
DASHBOARD_AFERIY_API_TOKEN=
DASHBOARD_AFERIY_TELEMETRY_TTL_S=90
```

Use `127.0.0.1` when Mosquitto and the dashboard run on the same Pi. Use the
broker IP address if the broker is on another machine.

On the Pi, watch all local MQTT traffic with:

```bash
mosquitto_sub -h 127.0.0.1 -p 1883 -t '#' -v
```
