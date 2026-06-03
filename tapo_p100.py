from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Awaitable, Callable

try:
    from kasa import (
        Credentials,
        Device,
        DeviceConfig,
        DeviceConnectionParameters,
        DeviceEncryptionType,
        DeviceFamily,
        Discover,
    )
except ImportError as exc:  # pragma: no cover - only used before dependencies exist.
    raise SystemExit(
        "Missing dependency: python-kasa. Install it with:\n"
        "  python -m pip install -r requirements.txt"
    ) from exc


DEFAULT_HOST = "192.168.1.107"
DEVICE_MAC = "98-BA-5F-C6-F0-A0"
ENV_FILE = Path(__file__).with_name(".env")


@dataclass(frozen=True)
class Settings:
    host: str
    username: str
    password: str
    timeout: int
    connection: str
    json_output: bool


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    load_env_file(ENV_FILE)

    parser = argparse.ArgumentParser(
        description="Control a TP-Link Tapo P100 over the local network."
    )
    parser.add_argument(
        "command",
        choices=("state", "on", "off", "toggle"),
        help="Action to run against the plug.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("TAPO_HOST", DEFAULT_HOST),
        help=f"Device IP address or hostname. Default: {DEFAULT_HOST}",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("TAPO_USERNAME"),
        help="TP-Link/Tapo account email. Can also use TAPO_USERNAME.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TAPO_PASSWORD"),
        help="TP-Link/Tapo account password. Can also use TAPO_PASSWORD.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("TAPO_TIMEOUT", "5")),
        help="Connection timeout in seconds. Default: 5",
    )
    parser.add_argument(
        "--connection",
        choices=("direct", "discover", "auto"),
        default=os.environ.get("TAPO_CONNECTION", "direct"),
        help="Connection strategy. Default: direct",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable state JSON.",
    )

    return parser.parse_args()


def build_settings(args: argparse.Namespace) -> Settings:
    username = args.username
    password = args.password

    if not username:
        raise SystemExit(
            "Missing Tapo username. Set TAPO_USERNAME in .env or pass --username."
        )

    if not password:
        if sys.stdin.isatty():
            password = getpass("TAPO_PASSWORD: ")
        else:
            raise SystemExit(
                "Missing Tapo password. Set TAPO_PASSWORD in .env or pass --password."
            )

    return Settings(
        host=args.host,
        username=username,
        password=password,
        timeout=args.timeout,
        connection=args.connection,
        json_output=args.json,
    )


def credentials(settings: Settings) -> Credentials:
    return Credentials(settings.username, settings.password)


async def connect_direct(settings: Settings) -> Device:
    connection_type = DeviceConnectionParameters(
        DeviceFamily.SmartTapoPlug,
        DeviceEncryptionType.Klap,
        login_version=2,
    )
    config = DeviceConfig(
        host=settings.host,
        timeout=settings.timeout,
        credentials=credentials(settings),
        connection_type=connection_type,
    )
    return await Device.connect(config=config)


async def connect_discover(settings: Settings) -> Device:
    device = await Discover.discover_single(
        settings.host,
        discovery_timeout=settings.timeout,
        timeout=settings.timeout,
        credentials=credentials(settings),
    )
    if device is None:
        raise RuntimeError(f"No supported Tapo/Kasa device responded at {settings.host}")

    await device.update()
    return device


async def connect_device(settings: Settings) -> Device:
    methods: list[tuple[str, Callable[[Settings], Awaitable[Device]]]]

    if settings.connection == "direct":
        methods = [("direct", connect_direct)]
    elif settings.connection == "discover":
        methods = [("discover", connect_discover)]
    else:
        methods = [("direct", connect_direct), ("discover", connect_discover)]

    errors: list[str] = []
    for name, method in methods:
        try:
            return await method(settings)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    details = "\n  ".join(errors)
    raise RuntimeError(
        f"Could not connect to {settings.host}.\n"
        f"  {details}\n"
        "Check the IP address, Wi-Fi reachability, credentials, and the Tapo "
        "Third-Party Compatibility setting."
    )


def state_payload(device: Device) -> dict[str, object]:
    return {
        "host": getattr(device, "host", None),
        "alias": getattr(device, "alias", None),
        "model": getattr(device, "model", None),
        "mac": getattr(device, "mac", DEVICE_MAC),
        "is_on": getattr(device, "is_on", None),
    }


def print_state(device: Device, *, json_output: bool) -> None:
    payload = state_payload(device)

    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    power = "on" if payload["is_on"] else "off"
    print(f"Host:  {payload['host']}")
    print(f"Name:  {payload['alias'] or '-'}")
    print(f"Model: {payload['model'] or '-'}")
    print(f"MAC:   {payload['mac'] or DEVICE_MAC}")
    print(f"Power: {power}")


async def run(settings: Settings, command: str) -> None:
    device = await connect_device(settings)
    try:
        if command == "on":
            await device.turn_on()
        elif command == "off":
            await device.turn_off()
        elif command == "toggle":
            await device.update()
            if device.is_on:
                await device.turn_off()
            else:
                await device.turn_on()

        await device.update()
        print_state(device, json_output=settings.json_output)
    finally:
        disconnect_result = device.disconnect()
        if inspect.isawaitable(disconnect_result):
            await disconnect_result


def main() -> int:
    args = parse_args()
    settings = build_settings(args)

    try:
        asyncio.run(run(settings, args.command))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
