from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from aferiy_p280 import (
    AferiyBleReader,
    AferiyMqttReader,
    build_aferiy_config,
    settings_payload as aferiy_settings_payload,
    static_payload as aferiy_static_payload,
)
from tapo_p100 import (
    DEFAULT_HOST,
    ENV_FILE,
    Settings,
    connect_device,
    load_env_file,
    state_payload,
)
from switchbot_meter import (
    SwitchBotConfig,
    SwitchBotOutdoorMeterBleReader,
    SwitchBotOutdoorMeterReader,
    build_switchbot_config,
)


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
TEMPERATURE_HISTORY_FILE = ROOT / "temperature_history.json"
TEMPERATURE_HISTORY_RANGES = {
    "day": {"seconds": 24 * 60 * 60, "bucket_seconds": 10 * 60},
    "week": {"seconds": 7 * 24 * 60 * 60, "bucket_seconds": 60 * 60},
    "month": {"seconds": 30 * 24 * 60 * 60, "bucket_seconds": 6 * 60 * 60},
}


@dataclass(frozen=True)
class DashboardConfig:
    title: str
    host: str
    port: int
    tapo_control_id: str
    tanks: list[dict[str, Any]]
    environment: dict[str, Any]
    battery: dict[str, Any]
    power_devices: list[dict[str, Any]]
    controls: list[dict[str, Any]]
    switchbot: SwitchBotConfig
    temperature_history_path: Path
    temperature_history_days: int
    temperature_history_sample_interval_s: int


CONTROL_DEFAULTS: tuple[dict[str, Any], ...] = (
    {
        "id": "lights",
        "label": "Lights",
        "icon": "light",
        "is_on": True,
    },
    {
        "id": "heater",
        "label": "Heater",
        "icon": "heat",
        "is_on": False,
    },
    {
        "id": "water_heater",
        "label": "Water Heater",
        "icon": "water",
        "is_on": True,
    },
    {
        "id": "interior_lights",
        "label": "Interior Lights",
        "icon": "interior",
        "is_on": True,
    },
)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number.") from exc


def env_auto_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default

    try:
        return int(value, 0)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc


def env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default

    path = Path(value.strip()).expanduser()
    if path.is_absolute():
        return path

    return ROOT / path


def tank(
    tank_id: str,
    label: str,
    icon: str,
    default_percent: int,
    default_capacity: int,
    default_litres: int,
    accent: str,
    default_channel: int,
) -> dict[str, Any]:
    prefix = f"DASHBOARD_{tank_id.upper()}_"
    percent = max(0, min(100, env_int(f"{prefix}PERCENT", default_percent)))
    capacity = max(1, env_int(f"{prefix}CAPACITY_L", default_capacity))
    litres = max(0, min(capacity, env_int(f"{prefix}LITRES", default_litres)))
    source = os.environ.get(
        f"{prefix}SOURCE",
        os.environ.get("DASHBOARD_TANK_SOURCE", "static"),
    ).strip().lower()
    if source not in {"static", "ads1115"}:
        raise SystemExit(f"{prefix}SOURCE must be static or ads1115.")

    payload: dict[str, Any] = {
        "id": tank_id.lower(),
        "label": label,
        "icon": icon,
        "percent": percent,
        "litres": litres,
        "capacity_litres": capacity,
        "accent": accent,
        "source": "static",
    }

    if source == "ads1115":
        channel = env_int(f"{prefix}ADC_CHANNEL", default_channel)
        if channel not in range(4):
            raise SystemExit(f"{prefix}ADC_CHANNEL must be between 0 and 3.")

        divider = os.environ.get(
            "DASHBOARD_TANK_DIVIDER",
            "sender_to_ground",
        ).strip().lower()
        if divider not in {"sender_to_ground", "sender_to_vcc"}:
            raise SystemExit(
                "DASHBOARD_TANK_DIVIDER must be sender_to_ground "
                "or sender_to_vcc."
            )

        payload["source"] = "ads1115"
        payload["sensor"] = {
            "address": env_auto_int("DASHBOARD_TANK_ADC_ADDRESS", 0x48),
            "gain": env_float("DASHBOARD_TANK_ADC_GAIN", 1.0),
            "supply_v": env_float("DASHBOARD_TANK_SUPPLY_V", 3.3),
            "fixed_ohms": env_float("DASHBOARD_TANK_FIXED_OHMS", 470.0),
            "divider": divider,
            "channel": channel,
            "empty_ohms": env_float(f"{prefix}EMPTY_OHMS", 0.0),
            "full_ohms": env_float(f"{prefix}FULL_OHMS", 190.0),
        }

    return payload


def build_config() -> DashboardConfig:
    load_env_file(ENV_FILE)

    tapo_control_id = os.environ.get(
        "DASHBOARD_TAPO_CONTROL_ID", "interior_lights"
    ).strip()
    control_ids = {control["id"] for control in CONTROL_DEFAULTS}
    if tapo_control_id not in control_ids:
        valid = ", ".join(sorted(control_ids))
        raise SystemExit(
            f"DASHBOARD_TAPO_CONTROL_ID must be one of: {valid}."
        )

    controls: list[dict[str, Any]] = []
    for control in CONTROL_DEFAULTS:
        control_id = control["id"]
        default_is_on = bool(control["is_on"])
        controls.append(
            {
                **control,
                "is_on": env_bool(
                    f"DASHBOARD_{control_id.upper()}_ON",
                    default_is_on,
                ),
                "source": "tapo" if control_id == tapo_control_id else "local",
            }
        )

    aferiy_config = build_aferiy_config()
    switchbot_config = build_switchbot_config()

    return DashboardConfig(
        title=os.environ.get("DASHBOARD_TITLE", "CAMPER VAN").strip()
        or "CAMPER VAN",
        host=os.environ.get("DASHBOARD_HOST", "127.0.0.1").strip()
        or "127.0.0.1",
        port=env_int("DASHBOARD_PORT", 8080),
        tapo_control_id=tapo_control_id,
        tanks=[
            tank("fresh", "Fresh Water", "water", 78, 100, 78, "#28b7ff", 0),
            tank("grey", "Grey Water", "grey", 45, 100, 45, "#98a7b5", 1),
        ],
        environment={
            "inside_c": env_int("DASHBOARD_INSIDE_TEMP_C", 20),
            "outside_c": env_int("DASHBOARD_OUTSIDE_TEMP_C", 22),
            "outside_source": switchbot_config.source,
        },
        battery={
            "percent": max(
                0,
                min(100, env_int("DASHBOARD_BATTERY_PERCENT", 85)),
            )
        },
        power_devices=(
            [
                {
                    "type": "aferiy_p280",
                    "config": aferiy_config,
                }
            ]
            if aferiy_config.enabled
            else []
        ),
        controls=controls,
        switchbot=switchbot_config,
        temperature_history_path=env_path(
            "DASHBOARD_TEMPERATURE_HISTORY_FILE",
            TEMPERATURE_HISTORY_FILE,
        ),
        temperature_history_days=max(
            1,
            env_int("DASHBOARD_TEMPERATURE_HISTORY_DAYS", 180),
        ),
        temperature_history_sample_interval_s=max(
            10,
            env_int("DASHBOARD_TEMPERATURE_SAMPLE_INTERVAL_S", 300),
        ),
    )


def tapo_settings() -> Settings:
    username = os.environ.get("TAPO_USERNAME")
    password = os.environ.get("TAPO_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "Missing TAPO_USERNAME or TAPO_PASSWORD in .env."
        )

    return Settings(
        host=os.environ.get("TAPO_HOST", DEFAULT_HOST),
        username=username,
        password=password,
        timeout=env_int("TAPO_TIMEOUT", 5),
        connection=os.environ.get("TAPO_CONNECTION", "direct"),
        json_output=True,
    )


async def read_tapo_state() -> dict[str, Any]:
    settings = tapo_settings()
    device = await connect_device(settings)
    try:
        await device.update()
        return state_payload(device)
    finally:
        disconnect_result = device.disconnect()
        if inspect.isawaitable(disconnect_result):
            await disconnect_result


async def set_tapo_power(action: str) -> dict[str, Any]:
    settings = tapo_settings()
    device = await connect_device(settings)
    try:
        if action == "on":
            await device.turn_on()
        elif action == "off":
            await device.turn_off()
        elif action == "toggle":
            await device.update()
            if device.is_on:
                await device.turn_off()
            else:
                await device.turn_on()
        else:
            raise ValueError("Action must be on, off, or toggle.")

        await device.update()
        return state_payload(device)
    finally:
        disconnect_result = device.disconnect()
        if inspect.isawaitable(disconnect_result):
            await disconnect_result


class TemperatureHistoryStore:
    def __init__(
        self,
        *,
        path: Path,
        sample_interval_s: int,
        retention_days: int,
    ) -> None:
        self.path = path
        self.sample_interval_s = sample_interval_s
        self.retention_seconds = retention_days * 24 * 60 * 60
        self.lock = threading.Lock()
        self.readings = self.load_readings()

    def load_readings(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            sys.stderr.write(f"Temperature history load failed: {exc}\n")
            return []

        raw_readings = body.get("readings", []) if isinstance(body, dict) else body
        if not isinstance(raw_readings, list):
            return []

        readings = [
            reading
            for item in raw_readings
            if (reading := self.clean_reading(item)) is not None
        ]
        readings.sort(key=lambda item: item["timestamp"])
        return readings

    @staticmethod
    def clean_number(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(number):
            return None

        return number

    @classmethod
    def clean_reading(cls, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        timestamp = cls.clean_number(item.get("timestamp"))
        if timestamp is None:
            return None

        reading: dict[str, Any] = {"timestamp": timestamp}
        for key in ("inside_c", "outside_c", "outside_humidity"):
            reading[key] = cls.clean_number(item.get(key))

        source = item.get("outside_source")
        if isinstance(source, str) and source:
            reading["outside_source"] = source

        if reading["inside_c"] is None and reading["outside_c"] is None:
            return None

        return reading

    def record_environment(self, environment: dict[str, Any]) -> None:
        now = time.time()
        reading = self.clean_reading(
            {
                "timestamp": now,
                "inside_c": environment.get("inside_c"),
                "outside_c": environment.get("outside_c"),
                "outside_humidity": environment.get("outside_humidity"),
                "outside_source": environment.get("outside_source"),
            }
        )
        if reading is None:
            return

        try:
            with self.lock:
                if (
                    self.readings
                    and now - float(self.readings[-1]["timestamp"])
                    < self.sample_interval_s
                ):
                    return

                self.readings.append(reading)
                self.prune_locked(now)
                self.write_locked()
        except Exception as exc:
            sys.stderr.write(f"Temperature history write failed: {exc}\n")

    def prune_locked(self, now: float) -> None:
        cutoff = now - self.retention_seconds
        self.readings = [
            reading
            for reading in self.readings
            if float(reading["timestamp"]) >= cutoff
        ]

    def write_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = {
            "version": 1,
            "readings": self.readings,
        }
        tmp_path.write_text(
            json.dumps(payload, indent=2, separators=(",", ": ")) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def payload(self, range_name: str) -> dict[str, Any]:
        if range_name not in TEMPERATURE_HISTORY_RANGES:
            range_name = "day"

        range_config = TEMPERATURE_HISTORY_RANGES[range_name]
        now = time.time()
        start = now - int(range_config["seconds"])
        bucket_seconds = int(range_config["bucket_seconds"])

        with self.lock:
            records = [
                dict(reading)
                for reading in self.readings
                if float(reading["timestamp"]) >= start
            ]
            latest = dict(self.readings[-1]) if self.readings else None
            total_samples = len(self.readings)

        return {
            "range": range_name,
            "start_ts": round(start),
            "end_ts": round(now),
            "bucket_seconds": bucket_seconds,
            "sample_count": len(records),
            "total_samples": total_samples,
            "latest": latest,
            "points": self.bucket_readings(records, start, bucket_seconds),
        }

    @staticmethod
    def bucket_readings(
        records: list[dict[str, Any]],
        start: float,
        bucket_seconds: int,
    ) -> list[dict[str, Any]]:
        buckets: dict[int, dict[str, Any]] = {}
        for record in records:
            timestamp = float(record["timestamp"])
            bucket_index = max(0, int((timestamp - start) // bucket_seconds))
            bucket = buckets.setdefault(
                bucket_index,
                {
                    "timestamp": start
                    + (bucket_index * bucket_seconds)
                    + (bucket_seconds / 2),
                    "inside_sum": 0.0,
                    "inside_count": 0,
                    "outside_sum": 0.0,
                    "outside_count": 0,
                    "humidity_sum": 0.0,
                    "humidity_count": 0,
                },
            )

            for record_key, sum_key, count_key in (
                ("inside_c", "inside_sum", "inside_count"),
                ("outside_c", "outside_sum", "outside_count"),
                ("outside_humidity", "humidity_sum", "humidity_count"),
            ):
                value = TemperatureHistoryStore.clean_number(record.get(record_key))
                if value is None:
                    continue
                bucket[sum_key] += value
                bucket[count_key] += 1

        points: list[dict[str, Any]] = []
        for bucket_index in sorted(buckets):
            bucket = buckets[bucket_index]
            points.append(
                {
                    "timestamp": round(float(bucket["timestamp"])),
                    "inside_c": TemperatureHistoryStore.average(
                        bucket["inside_sum"],
                        bucket["inside_count"],
                    ),
                    "outside_c": TemperatureHistoryStore.average(
                        bucket["outside_sum"],
                        bucket["outside_count"],
                    ),
                    "outside_humidity": TemperatureHistoryStore.average(
                        bucket["humidity_sum"],
                        bucket["humidity_count"],
                    ),
                }
            )

        return points

    @staticmethod
    def average(total: float, count: int) -> float | None:
        if count <= 0:
            return None

        return round(total / count, 1)


class DashboardState:
    def __init__(self, config: DashboardConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.adc_lock = threading.Lock()
        self.tapo_lock = threading.Lock()
        self.adc_channels: dict[tuple[int, float, int], Any] = {}
        self.aferiy_readers: dict[str, AferiyBleReader | AferiyMqttReader] = {}
        self.switchbot_reader = self.create_switchbot_reader(config.switchbot)
        self.temperature_history = TemperatureHistoryStore(
            path=config.temperature_history_path,
            sample_interval_s=config.temperature_history_sample_interval_s,
            retention_days=config.temperature_history_days,
        )
        self.local_controls = {
            control["id"]: bool(control["is_on"])
            for control in config.controls
            if control["source"] == "local"
        }
        self.start_power_readers()
        if self.switchbot_reader and hasattr(self.switchbot_reader, "start"):
            self.switchbot_reader.start()

        # Cache variables and background polling threads
        self.tapo_latest = None
        self.tapo_error = "Connecting..."
        self.tapo_thread_stop = threading.Event()
        self.tapo_thread = threading.Thread(
            target=self._tapo_poll_loop,
            name="tapo-status-poll",
            daemon=True,
        )
        self.tapo_thread.start()

        self.switchbot_latest = None
        self.switchbot_error = "Connecting..." if self.switchbot_reader else None
        self.switchbot_thread_stop = threading.Event()
        if self.switchbot_reader:
            self.switchbot_thread = threading.Thread(
                target=self._switchbot_poll_loop,
                name="switchbot-status-poll",
                daemon=True,
            )
            self.switchbot_thread.start()

    @staticmethod
    def create_switchbot_reader(config: SwitchBotConfig) -> Any:
        if config.source == "switchbot":
            return SwitchBotOutdoorMeterReader(config)
        if config.source == "switchbot_ble":
            return SwitchBotOutdoorMeterBleReader(config)
        return None

    def _tapo_poll_loop(self) -> None:
        while not self.tapo_thread_stop.is_set():
            tapo = None
            error = None
            try:
                with self.tapo_lock:
                    tapo = asyncio.run(read_tapo_state())
            except Exception as exc:
                error = str(exc)

            with self.lock:
                self.tapo_latest = tapo
                self.tapo_error = error

            # Sleep 10s checking for stop event
            for _ in range(100):
                if self.tapo_thread_stop.is_set():
                    break
                time.sleep(0.1)

    def _switchbot_poll_loop(self) -> None:
        while not self.switchbot_thread_stop.is_set():
            outdoor = None
            error = None
            try:
                outdoor = self.switchbot_reader.payload()
            except Exception as exc:
                error = str(exc)

            with self.lock:
                self.switchbot_latest = outdoor
                self.switchbot_error = error

            # Sleep 10s checking for stop event
            for _ in range(100):
                if self.switchbot_thread_stop.is_set():
                    break
                time.sleep(0.1)

    def start_power_readers(self) -> None:
        for device in self.config.power_devices:
            if device.get("type") != "aferiy_p280":
                continue

            config = device["config"]
            if config.source == "mqtt":
                reader = AferiyMqttReader(config)
            elif config.source == "ble":
                reader = AferiyBleReader(config)
            else:
                continue

            self.aferiy_readers["aferiy_p280"] = reader
            reader.start()

    def close(self) -> None:
        self.tapo_thread_stop.set()
        self.switchbot_thread_stop.set()
        if self.switchbot_reader and hasattr(self.switchbot_reader, "close"):
            self.switchbot_reader.close()
        for reader in self.aferiy_readers.values():
            reader.close()

    def power_payload(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for device in self.config.power_devices:
            if device.get("type") != "aferiy_p280":
                continue

            config = device["config"]
            if config.source in {"mqtt", "ble"}:
                reader = self.aferiy_readers.get("aferiy_p280")
                if reader:
                    payload.append(reader.payload())
                else:
                    item = aferiy_static_payload(config)
                    item.update(
                        {
                            "source": config.source,
                            "connected": False,
                            "error": (
                                f"AFERIY {config.source.upper()} reader did "
                                "not start."
                            ),
                        }
                    )
                    payload.append(item)
            else:
                payload.append(aferiy_static_payload(config))

        return payload

    def environment_payload(self) -> dict[str, Any]:
        payload = dict(self.config.environment)
        if not self.switchbot_reader:
            payload["outside_connected"] = True
            return payload

        with self.lock:
            outdoor = self.switchbot_latest
            error = self.switchbot_error

        if error:
            payload.update(
                {
                    "outside_c": None,
                    "outside_humidity": None,
                    "outside_battery_percent": None,
                    "outside_source": self.config.switchbot.source,
                    "outside_connected": False,
                    "outside_error": error,
                }
            )
        elif outdoor:
            payload.update(
                {
                    "outside_c": outdoor["temperature_c"],
                    "outside_humidity": outdoor["humidity_percent"],
                    "outside_battery_percent": outdoor["battery_percent"],
                    "outside_source": outdoor["source"],
                    "outside_connected": True,
                    "outdoor_sensor": outdoor,
                }
            )
        else:
            payload.update(
                {
                    "outside_c": None,
                    "outside_humidity": None,
                    "outside_battery_percent": None,
                    "outside_source": self.config.switchbot.source,
                    "outside_connected": False,
                    "outside_error": "Waiting for sensor data...",
                }
            )

        return payload

    def control_payload(
        self,
        *,
        tapo: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> list[dict[str, Any]]:
        controls: list[dict[str, Any]] = []
        for control in self.config.controls:
            payload = dict(control)
            if payload["source"] == "tapo":
                payload["is_on"] = tapo.get("is_on") if tapo else None
                payload["connected"] = bool(tapo and error is None)
                payload["error"] = error
            else:
                with self.lock:
                    payload["is_on"] = self.local_controls[payload["id"]]
                payload["connected"] = True
                payload["error"] = None

            controls.append(payload)

        return controls

    def tank_payload(self) -> list[dict[str, Any]]:
        return [self.tank_status(tank) for tank in self.config.tanks]

    def tank_status(self, tank_config: dict[str, Any]) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in tank_config.items()
            if key != "sensor"
        }
        sensor = tank_config.get("sensor")
        if tank_config.get("source") != "ads1115" or not sensor:
            return payload

        try:
            voltage = self.read_ads1115_voltage(sensor)
            resistance = self.sender_resistance(
                voltage=voltage,
                supply_v=sensor["supply_v"],
                fixed_ohms=sensor["fixed_ohms"],
                divider=sensor["divider"],
            )
            percent = self.percent_from_resistance(
                resistance,
                sensor["empty_ohms"],
                sensor["full_ohms"],
            )
            capacity = int(payload["capacity_litres"])
            payload.update(
                {
                    "percent": percent,
                    "litres": round(capacity * percent / 100),
                    "source": "ads1115",
                    "connected": True,
                    "voltage_v": round(voltage, 3),
                    "resistance_ohms": round(resistance, 1),
                }
            )
        except Exception as exc:
            payload["percent"] = None
            payload["litres"] = None
            payload["connected"] = False
            payload["sensor_error"] = str(exc)

        return payload

    def read_ads1115_voltage(self, sensor: dict[str, Any]) -> float:
        key = (
            int(sensor["address"]),
            float(sensor["gain"]),
            int(sensor["channel"]),
        )
        with self.adc_lock:
            channel = self.adc_channels.get(key)
            if channel is None:
                channel = self.create_ads1115_channel(*key)
                self.adc_channels[key] = channel

            return float(channel.voltage)

    @staticmethod
    def create_ads1115_channel(address: int, gain: float, channel: int) -> Any:
        try:
            import board
            import busio
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn
        except ImportError as exc:
            raise RuntimeError(
                "Missing ADS1115 dependency. Install it with: "
                "python -m pip install adafruit-circuitpython-ads1x15"
            ) from exc

        pins = (ADS.P0, ADS.P1, ADS.P2, ADS.P3)
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c, address=address)
        ads.gain = gain
        return AnalogIn(ads, pins[channel])

    @staticmethod
    def sender_resistance(
        *,
        voltage: float,
        supply_v: float,
        fixed_ohms: float,
        divider: str,
    ) -> float:
        if supply_v <= 0:
            raise RuntimeError("DASHBOARD_TANK_SUPPLY_V must be above 0.")
        if fixed_ohms <= 0:
            raise RuntimeError("DASHBOARD_TANK_FIXED_OHMS must be above 0.")

        if divider == "sender_to_ground":
            if voltage >= supply_v:
                raise RuntimeError("ADC voltage is at or above supply voltage.")
            return fixed_ohms * max(voltage, 0.0) / (supply_v - voltage)

        if voltage <= 0:
            raise RuntimeError("ADC voltage is at or below ground.")
        return fixed_ohms * (supply_v - voltage) / voltage

    @staticmethod
    def percent_from_resistance(
        resistance: float,
        empty_ohms: float,
        full_ohms: float,
    ) -> int:
        if empty_ohms == full_ohms:
            raise RuntimeError("Tank empty and full calibration cannot match.")

        percent = (resistance - empty_ohms) / (full_ohms - empty_ohms) * 100
        return max(0, min(100, round(percent)))

    def status_payload(self) -> dict[str, Any]:
        with self.lock:
            tapo = self.tapo_latest
            error = self.tapo_error

        environment = self.environment_payload()
        self.temperature_history.record_environment(environment)

        return {
            "title": self.config.title,
            "tanks": self.tank_payload(),
            "environment": environment,
            "battery": self.config.battery,
            "power_devices": self.power_payload(),
            "controls": self.control_payload(tapo=tapo, error=error),
            "tapo": {
                "control_id": self.config.tapo_control_id,
                "device": tapo,
                "connected": bool(tapo and error is None),
                "error": error,
            },
        }

    def temperature_history_payload(self, range_name: str) -> dict[str, Any]:
        return self.temperature_history.payload(range_name)

    def settings_payload(self) -> dict[str, Any]:
        return {
            "dashboard": {
                "title": self.config.title,
                "host": self.config.host,
                "port": self.config.port,
            },
            "tapo": {
                "host": os.environ.get("TAPO_HOST", DEFAULT_HOST),
                "connection": os.environ.get("TAPO_CONNECTION", "direct"),
                "timeout_s": os.environ.get("TAPO_TIMEOUT", "5"),
                "control_id": self.config.tapo_control_id,
                "username_configured": bool(os.environ.get("TAPO_USERNAME")),
                "password_configured": bool(os.environ.get("TAPO_PASSWORD")),
            },
            "tanks": [self.tank_settings(tank) for tank in self.config.tanks],
            "environment": dict(self.config.environment),
            "battery": dict(self.config.battery),
            "switchbot": {
                "enabled": self.config.switchbot.enabled,
                "source": self.config.switchbot.source,
                "timeout_s": self.config.switchbot.timeout,
                "ble_scan_seconds": self.config.switchbot.ble_scan_seconds,
                "token_configured": bool(self.config.switchbot.token),
                "secret_configured": bool(self.config.switchbot.secret),
                "device_id_configured": bool(self.config.switchbot.device_id),
                "ble_address_configured": bool(self.config.switchbot.ble_address),
                "device_name": self.config.switchbot.device_name,
            },
            "temperature_history": {
                "path": str(self.config.temperature_history_path),
                "retention_days": self.config.temperature_history_days,
                "sample_interval_s": self.config.temperature_history_sample_interval_s,
            },
            "power_devices": [
                aferiy_settings_payload(device["config"])
                for device in self.config.power_devices
                if device.get("type") == "aferiy_p280"
            ],
            "controls": [
                {
                    "id": control["id"],
                    "label": control["label"],
                    "icon": control["icon"],
                    "source": control["source"],
                }
                for control in self.config.controls
            ],
        }

    @staticmethod
    def tank_settings(tank_config: dict[str, Any]) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in tank_config.items()
            if key != "sensor"
        }
        sensor = tank_config.get("sensor")
        if sensor:
            payload["sensor"] = dict(sensor)

        return payload

    def update_control(self, control_id: str, action: str) -> dict[str, Any]:
        control = next(
            (
                item
                for item in self.config.controls
                if item["id"] == control_id
            ),
            None,
        )
        if control is None:
            raise KeyError(f"Unknown control: {control_id}")

        if action not in {"on", "off", "toggle"}:
            raise ValueError("Action must be on, off, or toggle.")

        if control["source"] == "tapo":
            with self.tapo_lock:
                tapo = asyncio.run(set_tapo_power(action))
            with self.lock:
                self.tapo_latest = tapo
                self.tapo_error = None
            controls = self.control_payload(tapo=tapo)
            return {
                "control": next(
                    item for item in controls if item["id"] == control_id
                ),
                "tapo": tapo,
            }

        with self.lock:
            if action == "toggle":
                self.local_controls[control_id] = not self.local_controls[control_id]
            else:
                self.local_controls[control_id] = action == "on"

            return {
                "control": {
                    "id": control_id,
                    "is_on": self.local_controls[control_id],
                    "source": "local",
                }
            }


class DashboardHandler(SimpleHTTPRequestHandler):
    server: "DashboardServer"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} - {format % args}\n")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.write_json(self.server.dashboard_state.status_payload())
            return

        if parsed.path == "/api/settings":
            self.write_json(self.server.dashboard_state.settings_payload())
            return

        if parsed.path == "/api/temperature-history":
            params = parse_qs(parsed.query)
            range_name = params.get("range", ["day"])[0]
            self.write_json(
                self.server.dashboard_state.temperature_history_payload(
                    range_name,
                )
            )
            return

        if parsed.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "controls"]:
            self.handle_control(parts[2])
            return

        self.write_json(
            {"error": "Not found."},
            status=HTTPStatus.NOT_FOUND,
        )

    def handle_control(self, control_id: str) -> None:
        try:
            payload = self.read_json_body()
            action = str(payload.get("action", "toggle")).lower()
            response = self.server.dashboard_state.update_control(
                control_id,
                action,
            )
            self.write_json(response)
        except KeyError as exc:
            self.write_json(
                {"error": str(exc)},
                status=HTTPStatus.NOT_FOUND,
            )
        except Exception as exc:
            self.write_json(
                {"error": str(exc)},
                status=HTTPStatus.BAD_REQUEST,
            )

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}

        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def write_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[DashboardHandler],
        dashboard_state: DashboardState,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        self.dashboard_state = dashboard_state

    def server_close(self) -> None:
        self.dashboard_state.close()
        super().server_close()


def parse_args() -> argparse.Namespace:
    load_env_file(ENV_FILE)
    parser = argparse.ArgumentParser(
        description="Run the local motorhome dashboard."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        help="Dashboard bind address. Default: 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=env_int("DASHBOARD_PORT", 8080),
        help="Dashboard port. Default: 8080",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = build_config()
    config = DashboardConfig(
        **{
            **config.__dict__,
            "host": args.host,
            "port": args.port,
        }
    )

    if not WEB_ROOT.exists():
        raise SystemExit(f"Missing web assets: {WEB_ROOT}")

    server = DashboardServer(
        (config.host, config.port),
        DashboardHandler,
        DashboardState(config),
    )
    url_host = "127.0.0.1" if config.host == "0.0.0.0" else config.host
    print(f"Dashboard running at http://{url_host}:{config.port}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
