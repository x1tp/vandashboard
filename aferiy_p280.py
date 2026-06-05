from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


API_BASE_URL = "https://api.app.sydpower.com/http/router/client/device"
API_GET_DEVICE_LIST = f"{API_BASE_URL}/saas.pub_getDeviceList"
REGISTER_MODBUS_ADDRESS = 17
REGISTER_COUNT = 80
BLE_SERVICE_UUID = "0000a002-0000-1000-8000-00805f9b34fb"
BLE_WRITE_CHAR_UUID = "0000c304-0000-1000-8000-00805f9b34fb"
BLE_NOTIFY_CHAR_UUID = "0000c305-0000-1000-8000-00805f9b34fb"
BLE_READ_RESPONSE_BYTES = 168
BLE_WRITE_RESPONSE_BYTES = 8
BLE_NAME_PREFIXES = ("POWER", "FOSSIBOT", "AFERIY", "SYDPOWER")
CONTROL_REGISTERS = {
    "usb": 24,
    "dc": 25,
    "ac": 26,
    "light": 27,
}
CONTROL_PAYLOAD_KEYS = {
    "usb": "usb_output_on",
    "dc": "dc_output_on",
    "ac": "ac_output_on",
    "light": "led_output_on",
}
DEFAULT_DEVICE_ID = ""
DEFAULT_LABEL = "AFERIY P280"
DEFAULT_MODEL = "P280"
DEFAULT_CAPACITY_WH = 2048
POLL_INTERVAL_S = 10


@dataclass(frozen=True)
class AferiyConfig:
    enabled: bool
    source: str
    label: str
    model: str
    capacity_wh: int
    percent: int
    input_w: int
    output_w: int
    ac_output_on: bool
    dc_output_on: bool
    usb_output_on: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_device_id: str
    mqtt_api_token: str
    ble_address: str
    ble_name_prefixes: tuple[str, ...]
    ble_scan_seconds: float
    ble_poll_seconds: float
    ble_timeout_s: float
    ble_service_uuid: str
    ble_write_char_uuid: str
    ble_notify_char_uuid: str
    telemetry_ttl_s: int


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer.") from exc


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number.") from exc


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_source(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip().lower()
    if value not in {"static", "mqtt", "ble"}:
        raise SystemExit(f"{name} must be static, mqtt, or ble.")

    return value


def env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default

    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_aferiy_config() -> AferiyConfig:
    return AferiyConfig(
        enabled=env_bool("DASHBOARD_AFERIY_ENABLED", True),
        source=env_source("DASHBOARD_AFERIY_SOURCE", "static"),
        label=os.environ.get("DASHBOARD_AFERIY_LABEL", DEFAULT_LABEL).strip()
        or DEFAULT_LABEL,
        model=os.environ.get("DASHBOARD_AFERIY_MODEL", DEFAULT_MODEL).strip()
        or DEFAULT_MODEL,
        capacity_wh=max(
            1,
            env_int("DASHBOARD_AFERIY_CAPACITY_WH", DEFAULT_CAPACITY_WH),
        ),
        percent=max(
            0,
            min(100, env_int("DASHBOARD_AFERIY_PERCENT", 85)),
        ),
        input_w=max(0, env_int("DASHBOARD_AFERIY_INPUT_W", 0)),
        output_w=max(0, env_int("DASHBOARD_AFERIY_OUTPUT_W", 0)),
        ac_output_on=env_bool("DASHBOARD_AFERIY_AC_OUTPUT_ON", False),
        dc_output_on=env_bool("DASHBOARD_AFERIY_DC_OUTPUT_ON", False),
        usb_output_on=env_bool("DASHBOARD_AFERIY_USB_OUTPUT_ON", False),
        mqtt_host=os.environ.get(
            "DASHBOARD_AFERIY_MQTT_HOST", "127.0.0.1"
        ).strip()
        or "127.0.0.1",
        mqtt_port=env_int("DASHBOARD_AFERIY_MQTT_PORT", 1883),
        mqtt_username=os.environ.get("DASHBOARD_AFERIY_MQTT_USERNAME", ""),
        mqtt_password=os.environ.get("DASHBOARD_AFERIY_MQTT_PASSWORD", ""),
        mqtt_device_id=os.environ.get(
            "DASHBOARD_AFERIY_MQTT_DEVICE_ID", DEFAULT_DEVICE_ID
        ).strip(),
        mqtt_api_token=os.environ.get("DASHBOARD_AFERIY_API_TOKEN", "").strip(),
        ble_address=os.environ.get("DASHBOARD_AFERIY_BLE_ADDRESS", "").strip(),
        ble_name_prefixes=env_csv(
            "DASHBOARD_AFERIY_BLE_NAME_PREFIXES",
            BLE_NAME_PREFIXES,
        ),
        ble_scan_seconds=max(
            1.0,
            env_float("DASHBOARD_AFERIY_BLE_SCAN_SECONDS", 10.0),
        ),
        ble_poll_seconds=max(
            2.0,
            env_float("DASHBOARD_AFERIY_BLE_POLL_SECONDS", 5.0),
        ),
        ble_timeout_s=max(
            3.0,
            env_float("DASHBOARD_AFERIY_BLE_TIMEOUT_S", 20.0),
        ),
        ble_service_uuid=os.environ.get(
            "DASHBOARD_AFERIY_BLE_SERVICE_UUID",
            BLE_SERVICE_UUID,
        ).strip()
        or BLE_SERVICE_UUID,
        ble_write_char_uuid=os.environ.get(
            "DASHBOARD_AFERIY_BLE_WRITE_CHAR_UUID",
            BLE_WRITE_CHAR_UUID,
        ).strip()
        or BLE_WRITE_CHAR_UUID,
        ble_notify_char_uuid=os.environ.get(
            "DASHBOARD_AFERIY_BLE_NOTIFY_CHAR_UUID",
            BLE_NOTIFY_CHAR_UUID,
        ).strip()
        or BLE_NOTIFY_CHAR_UUID,
        telemetry_ttl_s=max(5, env_int("DASHBOARD_AFERIY_TELEMETRY_TTL_S", 90)),
    )


def static_payload(config: AferiyConfig) -> dict[str, Any]:
    return {
        "id": "aferiy_p280",
        "label": config.label,
        "model": config.model,
        "capacity_wh": config.capacity_wh,
        "source": "static",
        "connected": True,
        "error": None,
        "percent": config.percent,
        "input_w": config.input_w,
        "output_w": config.output_w,
        "ac_output_on": config.ac_output_on,
        "dc_output_on": config.dc_output_on,
        "usb_output_on": config.usb_output_on,
        "led_output_on": False,
        "updated_at": None,
    }


def settings_payload(config: AferiyConfig) -> dict[str, Any]:
    return {
        "id": "aferiy_p280",
        "label": config.label,
        "model": config.model,
        "capacity_wh": config.capacity_wh,
        "enabled": config.enabled,
        "source": config.source,
        "mqtt": {
            "host": config.mqtt_host,
            "port": config.mqtt_port,
            "username_configured": bool(config.mqtt_username),
            "password_configured": bool(config.mqtt_password),
            "device_id_configured": bool(config.mqtt_device_id),
            "api_token_configured": bool(config.mqtt_api_token),
            "telemetry_ttl_s": config.telemetry_ttl_s,
        },
        "ble": {
            "address_configured": bool(config.ble_address),
            "name_prefixes": ", ".join(config.ble_name_prefixes),
            "scan_seconds": config.ble_scan_seconds,
            "poll_seconds": config.ble_poll_seconds,
            "timeout_s": config.ble_timeout_s,
            "service_uuid": config.ble_service_uuid,
        },
    }


def resolve_device_id(api_token: str) -> str:
    request = Request(
        API_GET_DEVICE_LIST,
        data=json.dumps({"api_token": api_token}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not fetch AFERIY device list: {exc}") from exc

    devices = body.get("rows") or body.get("data", {}).get("rows")
    if not isinstance(devices, list) or not devices:
        raise RuntimeError("AFERIY device list is empty.")

    first_device = devices[0]
    if not isinstance(first_device, dict):
        raise RuntimeError("AFERIY device list returned an unexpected payload.")

    device_id = str(
        first_device.get("device_id") or first_device.get("deviceId") or ""
    ).strip()
    if not device_id:
        raise RuntimeError("AFERIY device list did not include a deviceId.")

    return device_id


class AferiyMqttReader:
    def __init__(self, config: AferiyConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.client: Any | None = None
        self.device_id = config.mqtt_device_id
        self.topic_device_id = normalize_device_id(config.mqtt_device_id)
        self.connected = False
        self.started = False
        self.last_payload: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.poll_thread: threading.Thread | None = None
        self.poll_stop = threading.Event()

    def start(self) -> None:
        if self.started:
            return

        self.started = True
        if not self.device_id and self.config.mqtt_api_token:
            try:
                self.device_id = resolve_device_id(self.config.mqtt_api_token)
                self.topic_device_id = normalize_device_id(self.device_id)
            except Exception as exc:
                self.set_error(str(exc))
                return

        if not self.device_id:
            self.set_error(
                "Set DASHBOARD_AFERIY_MQTT_DEVICE_ID or "
                "DASHBOARD_AFERIY_API_TOKEN."
            )
            return

        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            self.set_error(
                "Missing paho-mqtt dependency. Install requirements.txt again."
            )
            return

        client_id = f"tapo-dashboard-{int(time.time())}"
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        if self.config.mqtt_username or self.config.mqtt_password:
            client.username_pw_set(
                self.config.mqtt_username,
                self.config.mqtt_password,
            )

        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        self.client = client

        try:
            client.connect_async(self.config.mqtt_host, self.config.mqtt_port, 30)
            client.loop_start()
            self.start_polling()
        except Exception as exc:
            self.set_error(f"Could not connect to AFERIY MQTT broker: {exc}")

    def close(self) -> None:
        if self.client is None:
            return

        try:
            self.poll_stop.set()
            if self.poll_thread and self.poll_thread.is_alive():
                self.poll_thread.join(timeout=2)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def start_polling(self) -> None:
        if self.poll_thread and self.poll_thread.is_alive():
            return

        self.poll_stop.clear()
        self.poll_thread = threading.Thread(
            target=self.poll_loop,
            name="aferiy-p280-poll",
            daemon=True,
        )
        self.poll_thread.start()

    def poll_loop(self) -> None:
        while not self.poll_stop.wait(POLL_INTERVAL_S):
            self.request_update()

    def request_update(self) -> None:
        client = self.client
        if client is None or not self.topic_device_id:
            return

        topic = f"{self.topic_device_id}/client/request/data"
        for command in (
            get_read_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_COUNT),
            get_read_input_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_COUNT),
        ):
            try:
                client.publish(topic, bytes(command), qos=1)
            except Exception as exc:
                self.set_error(f"Could not publish AFERIY read request: {exc}")

    def on_connect(
        self,
        client: Any,
        _userdata: Any,
        _flags: Any,
        result_code: int,
    ) -> None:
        if result_code != 0:
            self.set_error(f"AFERIY MQTT connection failed: {result_code}")
            return

        with self.lock:
            self.connected = True
            self.last_error = None

        base_topic = self.topic_device_id.strip("/")
        client.subscribe(
            [
                (f"{base_topic}/device/response/state", 1),
                (f"{base_topic}/device/response/client/+", 1),
            ]
        )
        self.request_update()

    def on_disconnect(
        self,
        _client: Any,
        _userdata: Any,
        result_code: int,
    ) -> None:
        with self.lock:
            self.connected = False
            if result_code != 0:
                self.last_error = f"AFERIY MQTT disconnected: {result_code}"

    def on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        topic = str(message.topic)
        if topic.endswith("/device/response/state"):
            with self.lock:
                self.connected = message.payload.strip() == b"1"
                self.last_error = None if self.connected else "AFERIY is offline."
            return

        payload = parse_modbus_payload(message.payload, topic)
        if payload is None:
            return

        with self.lock:
            current_payload = self.last_payload or base_payload(self.config, "mqtt")
            self.last_payload = {
                **current_payload,
                **payload,
                "connected": True,
                "error": None,
                "updated_at": int(time.time()),
            }
            self.last_error = None

    def set_error(self, message: str) -> None:
        with self.lock:
            self.connected = False
            self.last_error = message

    def payload(self) -> dict[str, Any]:
        with self.lock:
            payload = dict(self.last_payload or base_payload(self.config, "mqtt"))
            last_error = self.last_error
            connected = self.connected
            has_telemetry = self.last_payload is not None

        updated_at = payload.get("updated_at")
        is_stale = (
            isinstance(updated_at, int)
            and time.time() - updated_at > self.config.telemetry_ttl_s
        )
        if is_stale:
            connected = False
            last_error = "AFERIY telemetry is stale."

        payload["connected"] = bool(
            connected and has_telemetry and not last_error and not is_stale
        )
        payload["error"] = (
            last_error
            if last_error or has_telemetry
            else "Waiting for AFERIY telemetry."
        )
        return payload


class AferiyBleReader:
    def __init__(self, config: AferiyConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.started = False
        self.connected = False
        self.last_payload: dict[str, Any] | None = None
        self.last_error: str | None = "Starting AFERIY BLE reader."
        self.rx_buffer = bytearray()
        self.discovered_address: str | None = None
        self.discovered_name: str | None = None
        self.discovered_rssi: int | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: Any | None = None
        self.command_lock: asyncio.Lock | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        self.started = True
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self.thread_main,
            name="aferiy-p280-ble",
            daemon=True,
        )
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def thread_main(self) -> None:
        while not self.stop_event.is_set():
            try:
                asyncio.run(self.run_ble_session())
            except Exception as exc:
                self.set_error(f"AFERIY BLE connection failed: {exc}")

            if not self.stop_event.is_set():
                self.stop_event.wait(5)

    async def run_ble_session(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise RuntimeError(
                "Missing BLE dependency. Install it with: python -m pip install bleak"
            ) from exc

        target = await self.resolve_device(BleakScanner)
        self.set_error("Connecting to AFERIY over Bluetooth...")

        async with BleakClient(
            target,
            timeout=self.config.ble_timeout_s,
        ) as client:
            loop = asyncio.get_running_loop()
            command_lock = asyncio.Lock()
            with self.lock:
                self.connected = True
                self.client = client
                self.loop = loop
                self.command_lock = command_lock
                self.last_error = None
                self.rx_buffer.clear()

            await client.start_notify(
                self.config.ble_notify_char_uuid,
                self.on_notification,
            )

            last_settings_request = 0.0
            while not self.stop_event.is_set():
                await self.write_command(
                    client,
                    get_read_input_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_COUNT),
                )

                now = time.monotonic()
                if now - last_settings_request >= max(
                    self.config.ble_poll_seconds * 6,
                    30.0,
                ):
                    await asyncio.sleep(0.5)
                    await self.write_command(
                        client,
                        get_read_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_COUNT),
                    )
                    last_settings_request = now

                await asyncio.sleep(self.config.ble_poll_seconds)

            await client.stop_notify(self.config.ble_notify_char_uuid)

        with self.lock:
            self.connected = False
            self.client = None
            self.loop = None
            self.command_lock = None

    async def resolve_device(self, scanner: Any) -> Any:
        if self.config.ble_address:
            return self.config.ble_address

        self.set_error("Scanning for AFERIY BLE device...")
        devices = await self.discover_devices(scanner)
        prefixes = tuple(prefix.casefold() for prefix in self.config.ble_name_prefixes)
        for device, advertisement in devices:
            name = (
                getattr(device, "name", None)
                or getattr(advertisement, "local_name", None)
                or ""
            ).strip()
            service_uuids = [
                service_uuid.lower()
                for service_uuid in getattr(advertisement, "service_uuids", []) or []
            ]
            has_service = self.config.ble_service_uuid.lower() in service_uuids
            has_name = bool(name) and any(
                name.casefold().startswith(prefix)
                for prefix in prefixes
            )
            if not has_name and not has_service:
                continue

            with self.lock:
                self.discovered_address = getattr(device, "address", None)
                self.discovered_name = name or None
                self.discovered_rssi = getattr(advertisement, "rssi", None)
            return device

        expected = ", ".join(self.config.ble_name_prefixes) or "configured prefix"
        raise RuntimeError(
            "No AFERIY BLE device found. Set DASHBOARD_AFERIY_BLE_ADDRESS "
            f"or scan for a device named like: {expected}."
        )

    async def discover_devices(self, scanner: Any) -> list[tuple[Any, Any]]:
        try:
            discovered = await scanner.discover(
                timeout=self.config.ble_scan_seconds,
                return_adv=True,
            )
            return list(discovered.values())
        except TypeError:
            devices = await scanner.discover(timeout=self.config.ble_scan_seconds)
            return [(device, None) for device in devices]

    async def write_command(self, client: Any, command: list[int]) -> None:
        lock = self.command_lock
        if lock is None:
            await client.write_gatt_char(
                self.config.ble_write_char_uuid,
                bytes(command),
                response=False,
            )
            return

        async with lock:
            await client.write_gatt_char(
                self.config.ble_write_char_uuid,
                bytes(command),
                response=False,
            )

    def set_output(self, output_id: str, action: str) -> dict[str, Any]:
        if output_id not in CONTROL_REGISTERS:
            valid = ", ".join(sorted(CONTROL_REGISTERS))
            raise ValueError(f"Unknown AFERIY output. Use one of: {valid}.")

        if action not in {"on", "off", "toggle"}:
            raise ValueError("Action must be on, off, or toggle.")

        with self.lock:
            client = self.client
            loop = self.loop
            latest = dict(self.last_payload or {})
            connected = self.connected
            last_error = self.last_error

        if not connected or client is None or loop is None:
            raise RuntimeError(last_error or "AFERIY BLE is not connected.")

        if action == "toggle":
            current = latest.get(CONTROL_PAYLOAD_KEYS[output_id])
            if current is None:
                raise RuntimeError(
                    "Current output state is unknown. Wait for telemetry "
                    "then try again."
                )
            value = 0 if current else 1
        else:
            value = 1 if action == "on" else 0

        future = asyncio.run_coroutine_threadsafe(
            self.write_output_command(client, output_id, value),
            loop,
        )
        future.result(timeout=self.config.ble_timeout_s)
        return self.payload()

    async def write_output_command(
        self,
        client: Any,
        output_id: str,
        value: int,
    ) -> None:
        await self.write_command(
            client,
            get_write_modbus(
                REGISTER_MODBUS_ADDRESS,
                CONTROL_REGISTERS[output_id],
                value,
            ),
        )
        await asyncio.sleep(0.5)
        await self.write_command(
            client,
            get_read_input_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_COUNT),
        )

    def on_notification(self, _sender: Any, data: bytearray) -> None:
        for frame in self.extract_frames(bytes(data)):
            payload = parse_modbus_payload(frame, f"ble/{frame[1]:02x}")
            if payload is None:
                continue

            with self.lock:
                current_payload = self.last_payload or base_payload(
                    self.config,
                    "ble",
                )
                self.last_payload = {
                    **current_payload,
                    **payload,
                    "source": "ble",
                    "connected": True,
                    "error": None,
                    "updated_at": int(time.time()),
                    "ble_address": self.discovered_address
                    or self.config.ble_address
                    or None,
                    "ble_name": self.discovered_name,
                    "ble_rssi": self.discovered_rssi,
                }
                self.connected = True
                self.last_error = None

    def extract_frames(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        with self.lock:
            self.rx_buffer.extend(data)

            while len(self.rx_buffer) >= 2:
                if self.rx_buffer[0] != REGISTER_MODBUS_ADDRESS:
                    next_header = self.rx_buffer.find(
                        bytes([REGISTER_MODBUS_ADDRESS]),
                        1,
                    )
                    if next_header == -1:
                        self.rx_buffer.clear()
                        break
                    del self.rx_buffer[:next_header]

                function_code = self.rx_buffer[1]
                if function_code in {3, 4}:
                    expected_length = BLE_READ_RESPONSE_BYTES
                elif function_code == 6:
                    expected_length = BLE_WRITE_RESPONSE_BYTES
                else:
                    del self.rx_buffer[0]
                    continue

                if len(self.rx_buffer) < expected_length:
                    break

                frame = bytes(self.rx_buffer[:expected_length])
                del self.rx_buffer[:expected_length]
                if has_valid_modbus_crc(frame):
                    frames.append(frame)

        return frames

    def set_error(self, message: str) -> None:
        with self.lock:
            self.connected = False
            self.last_error = message

    def payload(self) -> dict[str, Any]:
        if not self.started:
            self.start()

        with self.lock:
            payload = dict(self.last_payload or base_payload(self.config, "ble"))
            last_error = self.last_error
            connected = self.connected
            has_telemetry = self.last_payload is not None
            ble_address = self.discovered_address or self.config.ble_address or None
            ble_name = self.discovered_name
            ble_rssi = self.discovered_rssi

        updated_at = payload.get("updated_at")
        is_stale = (
            isinstance(updated_at, int)
            and time.time() - updated_at > self.config.telemetry_ttl_s
        )
        if is_stale:
            connected = False
            last_error = "AFERIY BLE telemetry is stale."

        payload["connected"] = bool(
            connected and has_telemetry and not last_error and not is_stale
        )
        payload["error"] = (
            last_error
            if last_error or has_telemetry
            else "Waiting for AFERIY BLE telemetry."
        )
        payload["ble_address"] = payload.get("ble_address") or ble_address
        payload["ble_name"] = payload.get("ble_name") or ble_name
        payload["ble_rssi"] = payload.get("ble_rssi") or ble_rssi
        return payload


def base_payload(config: AferiyConfig, source: str) -> dict[str, Any]:
    return {
        "id": "aferiy_p280",
        "label": config.label,
        "model": config.model,
        "capacity_wh": config.capacity_wh,
        "source": source,
        "connected": False,
        "error": None,
        "percent": None,
        "input_w": None,
        "output_w": None,
        "ac_output_on": None,
        "dc_output_on": None,
        "usb_output_on": None,
        "led_output_on": None,
        "updated_at": None,
    }


def parse_modbus_payload(raw: bytes, topic: str) -> dict[str, Any] | None:
    registers = decode_registers(raw)
    if registers is None:
        return None

    if len(registers) < 57:
        return None

    function_code = raw[1] if len(raw) > 1 and raw[0] == REGISTER_MODBUS_ADDRESS else None
    if function_code == 4 or "device/response/client/04" in topic:
        active_outputs = registers[41]
        payload = {
            "percent": cap_percent(round(registers[56] / 10)),
            "input_w": registers[6],
            "output_w": registers[39],
            "ac_input_w": registers[3],
            "dc_input_w": registers[4],
            "ac_output_v": round(registers[18] / 10, 1),
            "ac_output_hz": round(registers[19] / 10, 1),
            "total_output_w": registers[20],
            "system_w": registers[21],
            "ac_input_hz": round(registers[22] / 100, 2),
            "usb_output_on": bool(active_outputs & 512),
            "dc_output_on": bool(active_outputs & 1024),
            "ac_output_on": bool(active_outputs & 2048),
            "led_output_on": bool(active_outputs & 4096),
            "time_to_full_min": registers[58] if len(registers) > 58 else None,
            "remaining_min": registers[59] if len(registers) > 59 else None,
        }
        if len(registers) > 53 and registers[53] > 0:
            payload["slave_1_percent"] = round(registers[53] / 10 - 1, 1)
        if len(registers) > 55 and registers[55] > 0:
            payload["slave_2_percent"] = round(registers[55] / 10 - 1, 1)
        return payload

    if function_code == 3 or "device/response/client/data" in topic:
        return {
            "ac_charging_rate": registers[13],
            "max_charging_current_a": registers[20],
            "ac_silent_charging": registers[57] == 1 if len(registers) > 57 else None,
        }

    return None


def decode_registers(raw: bytes) -> list[int] | None:
    if len(raw) < 8:
        return None

    data_end = len(raw) - 2 if has_valid_modbus_crc(raw) else len(raw)
    data_bytes = raw[6:data_end]
    if len(data_bytes) % 2:
        return None

    return [
        int.from_bytes(data_bytes[index : index + 2], "big")
        for index in range(0, len(data_bytes), 2)
    ]


def has_valid_modbus_crc(raw: bytes) -> bool:
    if len(raw) < 4:
        return False

    expected = crc16_modbus(list(raw[:-2]))
    actual = int.from_bytes(raw[-2:], "big")
    return expected == actual


def cap_percent(value: int) -> int:
    return max(0, min(100, int(value)))


def as_bool(value: int) -> bool:
    return bool(int(value))


def normalize_device_id(device_id: str) -> str:
    return device_id.replace(":", "").replace("-", "").strip()


def int_to_high_low(value: int) -> dict[str, int]:
    return {"low": value & 0xFF, "high": (value >> 8) & 0xFF}


def crc16_modbus(values: list[int]) -> int:
    crc = 0xFFFF
    for value in values:
        crc ^= value
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_modbus_command(
    address: int,
    function_code: int,
    start_register: int,
    register_count: int,
) -> list[int]:
    start = int_to_high_low(start_register)
    count_high = register_count >> 8
    count_low = register_count & 0xFF
    command = [
        address,
        function_code,
        start["high"],
        start["low"],
        count_high,
        count_low,
    ]
    checksum = int_to_high_low(crc16_modbus(command))
    return command + [checksum["high"], checksum["low"]]


def get_read_modbus(address: int, register_count: int) -> list[int]:
    return build_modbus_command(address, 3, 0, register_count)


def get_read_input_modbus(address: int, register_count: int) -> list[int]:
    return build_modbus_command(address, 4, 0, register_count)


def get_write_modbus(address: int, register: int, value: int) -> list[int]:
    return build_modbus_command(address, 6, register, value)
