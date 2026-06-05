from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = "https://api.switch-bot.com"
OUTDOOR_DEVICE_TYPE = "WoIOSensor"
OUTDOOR_BLE_COMPANY_ID = 0x0969
OUTDOOR_BLE_SERVICE_UUID = "0000fd3d-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True)
class SwitchBotConfig:
    source: str
    token: str
    secret: str
    device_id: str
    device_name: str
    timeout: int
    ble_address: str
    ble_scan_seconds: float

    @property
    def enabled(self) -> bool:
        return self.source in {"switchbot", "switchbot_ble"}


class SwitchBotApiError(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_switchbot_config() -> SwitchBotConfig:
    legacy_enabled = os.environ.get("DASHBOARD_SWITCHBOT_ENABLED")
    default_source = "switchbot" if _env_bool("DASHBOARD_SWITCHBOT_ENABLED", False) else "static"
    source = os.environ.get("DASHBOARD_OUTSIDE_TEMP_SOURCE", default_source).strip().lower()
    if legacy_enabled is not None and _env_bool("DASHBOARD_SWITCHBOT_ENABLED", False):
        source = "switchbot"
    if source not in {"static", "switchbot", "switchbot_ble"}:
        raise SystemExit(
            "DASHBOARD_OUTSIDE_TEMP_SOURCE must be static, switchbot, "
            "or switchbot_ble."
        )

    try:
        timeout = int(os.environ.get("SWITCHBOT_TIMEOUT", "8"))
    except ValueError as exc:
        raise SystemExit("SWITCHBOT_TIMEOUT must be an integer.") from exc

    try:
        ble_scan_seconds = float(os.environ.get("SWITCHBOT_BLE_SCAN_SECONDS", "10"))
    except ValueError as exc:
        raise SystemExit("SWITCHBOT_BLE_SCAN_SECONDS must be a number.") from exc

    return SwitchBotConfig(
        source=source,
        token=os.environ.get("SWITCHBOT_TOKEN", "").strip(),
        secret=os.environ.get("SWITCHBOT_SECRET", "").strip(),
        device_id=os.environ.get("SWITCHBOT_DEVICE_ID", "").strip(),
        device_name=os.environ.get("SWITCHBOT_DEVICE_NAME", "").strip(),
        timeout=timeout,
        ble_address=os.environ.get("SWITCHBOT_BLE_ADDRESS", "").strip(),
        ble_scan_seconds=ble_scan_seconds,
    )


class SwitchBotOutdoorMeterReader:
    def __init__(self, config: SwitchBotConfig) -> None:
        self.config = config
        self.device_id = config.device_id

    def payload(self) -> dict[str, Any]:
        body = self.device_status()
        temperature = self._number(body.get("temperature"))
        if temperature is None:
            raise SwitchBotApiError(
                "SwitchBot status response did not include temperature. "
                "Check the sensor is linked to a SwitchBot hub."
            )

        return {
            "id": "switchbot_outdoor_meter",
            "source": "switchbot",
            "connected": True,
            "device_id": body.get("deviceId") or self.device_id,
            "device_type": body.get("deviceType"),
            "hub_device_id": body.get("hubDeviceId"),
            "version": body.get("version"),
            "temperature_c": temperature,
            "humidity_percent": self._integer(body.get("humidity")),
            "battery_percent": self._integer(body.get("battery")),
            "updated_at": int(time.time()),
        }

    def device_status(self) -> dict[str, Any]:
        device_id = self.resolve_device_id()
        return self.get_json(f"/v1.1/devices/{quote(device_id)}/status")

    def resolve_device_id(self) -> str:
        if self.device_id:
            return self.device_id

        devices = self.get_json("/v1.1/devices").get("deviceList", [])
        if not isinstance(devices, list):
            raise SwitchBotApiError("SwitchBot device list response was invalid.")

        candidates = [
            device
            for device in devices
            if isinstance(device, dict)
            and device.get("deviceType") == OUTDOOR_DEVICE_TYPE
        ]
        if self.config.device_name:
            wanted = self.config.device_name.casefold()
            candidates = [
                device
                for device in candidates
                if str(device.get("deviceName", "")).casefold() == wanted
            ]

        if not candidates:
            hint = (
                f' named "{self.config.device_name}"'
                if self.config.device_name
                else ""
            )
            raise SwitchBotApiError(f"No SwitchBot Outdoor Meter{hint} found.")

        device_id = str(candidates[0].get("deviceId", "")).strip()
        if not device_id:
            raise SwitchBotApiError("SwitchBot Outdoor Meter did not include a deviceId.")

        self.device_id = device_id
        return device_id

    def get_json(self, path: str) -> dict[str, Any]:
        self.require_credentials()
        request = Request(
            f"{BASE_URL}{path}",
            headers=self.headers(),
            method="GET",
        )

        try:
            with urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SwitchBotApiError(
                f"SwitchBot API returned HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise SwitchBotApiError(f"SwitchBot API connection failed: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SwitchBotApiError("SwitchBot API returned invalid JSON.") from exc

        if payload.get("statusCode") != 100:
            message = payload.get("message") or "unknown error"
            raise SwitchBotApiError(f"SwitchBot API error: {message}")

        body = payload.get("body")
        if not isinstance(body, dict):
            raise SwitchBotApiError("SwitchBot API response did not include a body object.")

        return body

    def headers(self) -> dict[str, str]:
        nonce = str(uuid.uuid4())
        timestamp = str(int(round(time.time() * 1000)))
        string_to_sign = f"{self.config.token}{timestamp}{nonce}".encode("utf-8")
        secret = self.config.secret.encode("utf-8")
        sign = base64.b64encode(
            hmac.new(secret, string_to_sign, hashlib.sha256).digest()
        ).decode("utf-8")

        return {
            "Authorization": self.config.token,
            "Content-Type": "application/json",
            "charset": "utf8",
            "t": timestamp,
            "sign": sign,
            "nonce": nonce,
        }

    def require_credentials(self) -> None:
        missing = [
            name
            for name, value in {
                "SWITCHBOT_TOKEN": self.config.token,
                "SWITCHBOT_SECRET": self.config.secret,
            }.items()
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise SwitchBotApiError(f"Missing {joined} in .env.")

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class SwitchBotOutdoorMeterBleReader:
    def __init__(self, config: SwitchBotConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.latest: dict[str, Any] | None = None
        self.error = "Waiting for SwitchBot Outdoor Meter BLE advertisement."

    def payload(self) -> dict[str, Any]:
        self.start()
        deadline = time.monotonic() + self.config.ble_scan_seconds
        while time.monotonic() < deadline:
            with self.lock:
                if self.latest:
                    return dict(self.latest)
                error = self.error
            time.sleep(0.2)

        with self.lock:
            if self.latest:
                return dict(self.latest)
            error = self.error

        raise SwitchBotApiError(error)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._thread_main,
            name="switchbot-ble-monitor",
            daemon=True,
        )
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._scan_loop())
        except Exception as exc:
            with self.lock:
                self.error = str(exc)

    async def _scan_loop(self) -> None:
        try:
            from bleak import BleakScanner
        except ImportError as exc:
            raise SwitchBotApiError(
                "Missing BLE dependency. Install it with: python -m pip install bleak"
            ) from exc

        expected = self.expected_identifiers()

        def callback(device: Any, advertisement: Any) -> None:
            manufacturer = bytes(
                advertisement.manufacturer_data.get(
                    OUTDOOR_BLE_COMPANY_ID,
                    b"",
                )
            )
            service_data = bytes(
                advertisement.service_data.get(OUTDOOR_BLE_SERVICE_UUID, b"")
            )
            if not manufacturer or not service_data:
                return

            candidate = self.parse_advertisement(
                address=device.address,
                name=device.name or advertisement.local_name,
                rssi=advertisement.rssi,
                manufacturer=manufacturer,
                service_data=service_data,
            )
            if (
                expected
                and candidate["device_id"] not in expected
                and candidate["ble_address"] not in expected
            ):
                return

            with self.lock:
                self.latest = {
                    **candidate,
                    "id": "switchbot_outdoor_meter",
                    "source": "switchbot_ble",
                    "connected": True,
                    "updated_at": int(time.time()),
                }
                self.error = ""

        while not self.stop_event.is_set():
            scanner = BleakScanner(callback)
            try:
                await scanner.start()
                while not self.stop_event.is_set():
                    await asyncio.sleep(0.5)
            except Exception as exc:
                with self.lock:
                    self.error = f"SwitchBot BLE scan failed: {exc}"
                await asyncio.sleep(5)
            finally:
                await scanner.stop()

    def expected_identifiers(self) -> set[str]:
        identifiers = {
            self.normalized_device_id(self.config.device_id),
            self.normalized_device_id(self.config.ble_address),
        }
        return {identifier for identifier in identifiers if identifier}

    @classmethod
    def parse_advertisement(
        cls,
        *,
        address: str,
        name: str | None,
        rssi: int | None,
        manufacturer: bytes,
        service_data: bytes,
    ) -> dict[str, Any]:
        if len(manufacturer) < 11:
            raise SwitchBotApiError("Outdoor Meter manufacturer data is too short.")

        sign = 1 if manufacturer[9] & 0x80 else -1
        temperature = round(
            ((manufacturer[8] & 0x0F) * 0.1 + (manufacturer[9] & 0x7F)) * sign,
            1,
        )
        humidity = manufacturer[10] & 0x7F
        battery = service_data[2] & 0x7F if len(service_data) >= 3 else None
        device_id = manufacturer[:6].hex().upper()

        return {
            "device_id": device_id,
            "ble_address": cls.normalized_device_id(address),
            "name": name,
            "rssi": rssi,
            "temperature_c": temperature,
            "humidity_percent": humidity,
            "battery_percent": battery,
        }

    @staticmethod
    def normalized_device_id(value: str) -> str:
        return "".join(character for character in value.upper() if character.isalnum())
