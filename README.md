# Local Tapo P100 Control

This controls the Tapo P100 at `192.168.1.107` over the LAN using
`python-kasa`. It does not send on/off commands through the Tapo cloud, but the
plug still uses your TP-Link/Tapo credentials for local authentication.

## One-time Tapo setup

In the Tapo app, enable third-party local access:

`Me > Third-Party Services > Third-Party Compatibility`

Keep the router DHCP reservation pinned to:

`98-BA-5F-C6-F0-A0 -> 192.168.1.107`

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Edit `.env` and enter your TP-Link/Tapo account email and password.

## Use

```powershell
.\.venv\Scripts\python.exe .\tapo_p100.py state
.\.venv\Scripts\python.exe .\tapo_p100.py on
.\.venv\Scripts\python.exe .\tapo_p100.py off
.\.venv\Scripts\python.exe .\tapo_p100.py toggle
```

## Dashboard

Run the local always-on dashboard:

```powershell
.\.venv\Scripts\python.exe .\dashboard.py
```

Open:

`http://127.0.0.1:8080`

The dashboard uses the bottom-right dark HUD style from the reference image. It
serves static HTML/CSS/JavaScript from `web/` and provides local JSON endpoints
from `dashboard.py`, so there is no Node build step or external CDN.

Set `DASHBOARD_TAPO_CONTROL_ID` in `.env` to choose which dashboard button maps
to the real P100. Valid values are:

`lights`, `heater`, `water_heater`, `interior_lights`

Only that configured control sends commands to the Tapo plug. The other controls
are local dashboard states until you wire them to real hardware or APIs.

You can also adjust the fallback display values in `.env`, including tank
levels, temperature, battery percentage, title, host, and port.

## Temperature History

The bottom Climate button opens a temperature history page with Day, Week, and
Month graph ranges. The dashboard records the current inside and outside
readings into `temperature_history.json` every five minutes by default.

Optional `.env` settings:

```dotenv
DASHBOARD_TEMPERATURE_HISTORY_FILE=temperature_history.json
DASHBOARD_TEMPERATURE_SAMPLE_INTERVAL_S=300
DASHBOARD_TEMPERATURE_HISTORY_DAYS=180
```

## SwitchBot Outdoor Meter

The dashboard can read a SwitchBot W3400010 Outdoor Meter for the Outside
temperature and humidity through SwitchBot OpenAPI.

Requirements:

- the Outdoor Meter is added in the SwitchBot app
- a SwitchBot Hub Mini, Hub 2, Hub Mini Matter Enabled, or Hub 3 is added in
  the app and within Bluetooth range of the meter
- SwitchBot OpenAPI token and secret are configured in `.env`

In the SwitchBot app, go to `Profile > Preferences > About`, tap `App Version`
10 times, then open `Developer Options > Get Token`.

Set these values in `.env`:

```dotenv
DASHBOARD_OUTSIDE_TEMP_SOURCE=switchbot
SWITCHBOT_TOKEN=your-switchbot-open-token
SWITCHBOT_SECRET=your-switchbot-secret

# Optional. Leave blank to auto-discover the first W3400010 Outdoor Meter.
SWITCHBOT_DEVICE_ID=
SWITCHBOT_DEVICE_NAME=
SWITCHBOT_TIMEOUT=8
```

The browser refreshes the dashboard every 10 seconds. That gives near realtime
readings without needing a local Bluetooth integration. If SwitchBot is
configured but unavailable, the Outside display shows `--°C` and the Settings
screen shows the API error.

If the cloud API can see the meter but returns empty readings, use local BLE
polling instead. This requires Bluetooth on the dashboard machine and the meter
within radio range:

```dotenv
DASHBOARD_OUTSIDE_TEMP_SOURCE=switchbot_ble
SWITCHBOT_DEVICE_ID=DA0F7A4163B8
SWITCHBOT_BLE_SCAN_SECONDS=10
```

`SWITCHBOT_DEVICE_ID` can be the SwitchBot cloud ID without colons, or
`SWITCHBOT_BLE_ADDRESS` can be the Bluetooth address with or without colons.

The dashboard can also show the AFERIY P280 as a power device. It starts with
static fallback values and can be switched to local Bluetooth polling so the
power station does not need to stay connected to Wi-Fi. BrightEMS local MQTT is
still available as a fallback option. See [docs/aferiy-p280.md](docs/aferiy-p280.md).

For automation:

```powershell
.\.venv\Scripts\python.exe .\tapo_p100.py state --json
```

## Raspberry Pi

This should work well on a Raspberry Pi because it is a lightweight Python web
server plus static browser UI. On Raspberry Pi OS:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-pi.txt
cp .env.example .env
nano .env
python dashboard.py --host 127.0.0.1 --port 8080
```

Open Chromium full screen on the Pi:

```bash
chromium-browser --kiosk http://127.0.0.1:8080
```

To make it visible from another device on your motorhome network, set
`DASHBOARD_HOST=0.0.0.0` and open `http://<pi-ip>:8080`. Do not expose this
dashboard to the public internet.

For an always-on install, run `dashboard.py` as a `systemd` service and launch
Chromium in kiosk mode from the desktop autostart. Disable screen blanking in
Raspberry Pi configuration if the display should stay on permanently.

## Tank Level Sensors

The 0-190 ohm sender is a variable resistor, not a digital sensor. Use an
ADS1115 ADC on I2C and read the sender through a 3.3V voltage divider.

Full wiring instructions are in
[docs/tank-sensor-wiring.md](docs/tank-sensor-wiring.md).

Install the Pi dependencies before enabling live tank readings:

```bash
. .venv/bin/activate
python -m pip install -r requirements-pi.txt
sudo raspi-config
```

Enable I2C in `raspi-config`, wire the ADS1115 as documented, then set:

```dotenv
DASHBOARD_TANK_SOURCE=ads1115
DASHBOARD_TANK_ADC_ADDRESS=0x48
DASHBOARD_TANK_SUPPLY_V=3.3
DASHBOARD_TANK_FIXED_OHMS=470
DASHBOARD_TANK_DIVIDER=sender_to_ground
DASHBOARD_FRESH_ADC_CHANNEL=0
DASHBOARD_FRESH_EMPTY_OHMS=0
DASHBOARD_FRESH_FULL_OHMS=190
DASHBOARD_GREY_ADC_CHANNEL=1
DASHBOARD_GREY_EMPTY_OHMS=0
DASHBOARD_GREY_FULL_OHMS=190
```

If the reading moves backwards, swap the empty and full ohm values for that
tank. When sensor mode is enabled and the ADC is unavailable, the dashboard
shows `--%` and `Sensor offline` instead of placeholder tank levels.

## If connection fails

Try the discovery path:

```powershell
.\.venv\Scripts\python.exe .\tapo_p100.py state --connection auto
```

If you get an authentication or handshake error:

- confirm `.env` uses the exact Tapo account email, preferably lowercase
- disable and re-enable Third-Party Compatibility in the Tapo app
- let the plug reach the internet once after changing account/app settings, then
  retry local control
- if it still fails after a firmware update, factory reset the plug, add it back
  to Tapo, enable Third-Party Compatibility, and retry

You can also use the installed `kasa` CLI directly:

```powershell
.\.venv\Scripts\kasa.exe --host 192.168.1.107 --type smart --username "you@example.com" --password "password" state
.\.venv\Scripts\kasa.exe --host 192.168.1.107 --type smart --username "you@example.com" --password "password" on
```
