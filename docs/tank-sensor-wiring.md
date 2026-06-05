# Tank Sender Wiring With ADS1115

This guide wires 0-190 ohm tank senders to a Raspberry Pi for the dashboard
tank level display.

## Will This ADS1115 Module Work?

Yes, if the board is a normal ADS1115 breakout with these pins:

- `VDD`
- `GND`
- `SCL`
- `SDA`
- `ADDR`
- `ALRT`
- `A0`, `A1`, `A2`, `A3`

Use one ADS1115 board for both fresh water and grey waste. The board has four
single-ended analog inputs, so this project uses:

- `A0` for fresh water
- `A1` for grey waste

The second board in the two-pack is spare.

## Important Limits

- Power the ADS1115 from the Pi `3V3` pin, not `5V`.
- Do not connect the sender directly to a Raspberry Pi GPIO pin.
- Do not connect any 12V gauge wire to the Pi or ADS1115.
- Do not let `A0`, `A1`, `A2`, or `A3` see more than the ADS1115 supply voltage.
- If a sender is already connected to a vehicle gauge, disconnect it from that
  gauge circuit before using this wiring.

The sender is just a variable resistor. The Pi cannot read resistance directly,
so the ADS1115 reads a voltage from a resistor divider.

## Parts

- Raspberry Pi with I2C enabled
- 1 ADS1115 module
- 2 x 0-190 ohm tank senders
- 2 x 470 ohm resistors, preferably 1 percent tolerance
- Hookup wire
- Optional: 2 x 0.1 uF capacitors for smoothing noisy readings

## Raspberry Pi To ADS1115 Wiring

Power the ADS1115 from `3V3` so the I2C pullups and ADC inputs stay Pi-safe.

| Raspberry Pi pin | Raspberry Pi signal | ADS1115 pin |
| --- | --- | --- |
| Pin 1 | `3V3` | `VDD` |
| Pin 6 | `GND` | `GND` |
| Pin 3 | `GPIO2 / SDA` | `SDA` |
| Pin 5 | `GPIO3 / SCL` | `SCL` |

Leave `ALRT` disconnected.

Connect `ADDR` to `GND`, or leave it alone if the module already defaults to
address `0x48`. The dashboard expects `0x48` unless you change
`DASHBOARD_TANK_ADC_ADDRESS`.

## Tank Sender Divider Wiring

Wire each sender as the lower half of a divider:

```text
Pi 3V3
  |
  | 470 ohm resistor
  |
  +---- ADS1115 A0 or A1
  |
  | tank sender, 0-190 ohm
  |
GND
```

Fresh water:

```text
Pi 3V3 -> 470 ohm resistor -> ADS1115 A0 -> fresh sender -> GND
```

Grey waste:

```text
Pi 3V3 -> 470 ohm resistor -> ADS1115 A1 -> grey sender -> GND
```

Optional smoothing capacitor:

```text
ADS1115 A0/A1 -> 0.1 uF capacitor -> GND
```

Put the capacitor near the ADS1115 input if the reading jumps around.

## Expected Voltages

With `3.3V` supply and a `470 ohm` fixed resistor:

| Sender resistance | Approx ADC voltage |
| --- | ---: |
| 0 ohm | 0.00 V |
| 95 ohm | 0.55 V |
| 190 ohm | 0.95 V |

These voltages are safely inside the ADS1115 input range when the ADS1115 is
powered from `3V3`.

## Enable I2C On The Pi

```bash
sudo raspi-config
```

Then enable:

```text
Interface Options -> I2C
```

Reboot if prompted.

Install the ADS1115 Python library inside the project virtual environment:

```bash
. .venv/bin/activate
python -m pip install -r requirements-pi.txt
```

Optional check that the Pi can see the board:

```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
```

You should normally see `48` in the address table.

## Dashboard Configuration

Set these values in `.env` on the Raspberry Pi:

```dotenv
DASHBOARD_TANK_SOURCE=ads1115
DASHBOARD_TANK_ADC_ADDRESS=0x48
DASHBOARD_TANK_ADC_GAIN=1
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

Restart the dashboard after editing `.env`.

## First Power-Up Checks

Before connecting the ADS1115 to the Pi, measure these with a multimeter:

- ADS1115 `VDD` to `GND`: about `3.3V`
- `A0` to `GND`: between `0V` and `3.3V`
- `A1` to `GND`: between `0V` and `3.3V`
- `SDA` to `GND`: not above `3.3V`
- `SCL` to `GND`: not above `3.3V`

Then start the dashboard:

```bash
. .venv/bin/activate
python dashboard.py --host 127.0.0.1 --port 8080
```

In another terminal, check the tank payload:

```bash
curl http://127.0.0.1:8080/api/status
```

Each tank should report `"source":"ads1115"` and `"connected":true` when the
ADC is being used. If a sensor read fails, the dashboard shows `--%` and
`Sensor offline`, and the API adds a `sensor_error` field to that tank payload.

## Calibration

The starting calibration assumes:

- `0 ohm` = empty
- `190 ohm` = full

If the dashboard moves backwards, swap the two values for that tank:

```dotenv
DASHBOARD_FRESH_EMPTY_OHMS=190
DASHBOARD_FRESH_FULL_OHMS=0
```

For better calibration, measure the sender resistance with the tank empty and
full, then enter those measured values.

## References

- Texas Instruments ADS1115 product page and datasheet:
  https://www.ti.com/product/ADS1115
- Raspberry Pi GPIO documentation:
  https://www.raspberrypi.com/documentation/computers/raspberry-pi.html
- Adafruit ADS1x15 Python library:
  https://docs.circuitpython.org/projects/ads1x15/
