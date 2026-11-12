"""Bluetooth side of the bridge: find the lights, connect, and send frames to them.

protocol.py decides which bytes to send; this file only moves them over Bluetooth. server.py
calls these functions and keeps the one open connection.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

import protocol

logger = logging.getLogger("lights")

LIGHTS_NAME = "Haxagon Lights"
SCAN_SECONDS = 10.0
# Vendor-specific 0xfff0 service: commands are written to 0xfff3 and replies arrive on 0xfff4.
COMMAND_CHARACTERISTIC_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"
REPLY_CHARACTERISTIC_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"
# The lights put their identity in manufacturer data under this company ID (0xFFFF is reserved
# for "unassigned", which cheap controllers use).
MANUFACTURER_DATA_KEY = 0xFFFF
# Pause after the handshake so the lights are ready, like the gap between the app's frames.
HANDSHAKE_SETTLE_SECONDS = 0.2


class LightsNotFoundError(Exception):
    """The lights did not show up in a scan, usually because they are off or already connected."""


@dataclass
class LightsConnection:
    """An open Bluetooth connection to the lights, plus the lock that keeps their frames in order.

    Writes take the lock so two quick UI events cannot interleave their frames.
    """

    client: BleakClient
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def is_lights_connected(connection: LightsConnection | None) -> bool:
    """Whether there is a connection and its Bluetooth link is still up.

    The lights can drop the link on their own (power off, out of range), so a stored connection
    is not proof. None means we never connected.
    """
    return connection is not None and connection.client.is_connected


async def connect_to_lights() -> LightsConnection:
    """Scan for the lights, connect, subscribe to replies and perform the app's handshake."""
    advertisement_bytes, device = await find_lights()
    client = BleakClient(device)
    await client.connect()
    await client.start_notify(REPLY_CHARACTERISTIC_UUID, log_reply)
    connection = LightsConnection(client)
    await send_frame(connection, protocol.handshake_frame(advertisement_bytes))
    await asyncio.sleep(HANDSHAKE_SETTLE_SECONDS)
    await send_frame(connection, protocol.clock_sync_frame(datetime.now()))
    return connection


async def disconnect_from_lights(connection: LightsConnection) -> None:
    """Close the link so the phone app can connect again: the lights accept one client at a time."""
    await connection.client.disconnect()


async def send_frame(connection: LightsConnection, frame: bytes) -> None:
    """Write one frame to the lights without waiting for a Bluetooth-level acknowledgement.

    The app writes without response too; the lights answer separately on the reply characteristic.
    """
    async with connection.write_lock:
        logger.info("send  %s", frame.hex(" "))
        await connection.client.write_gatt_char(COMMAND_CHARACTERISTIC_UUID, frame, response=False)


async def find_lights() -> tuple[bytes, BLEDevice]:
    """Scan until the lights appear; return their advertised identity bytes and the device.

    Stops the moment they show up, usually within a second; scanning for the full time first
    made every connect take over 10 seconds. Raises LightsNotFoundError if they are not
    advertising. They stop advertising while any other device (the phone app, or a leftover
    bluetoothctl session) holds a connection.
    """
    # find_device_by_filter returns only the device, so the filter keeps the advertisement that
    # matched: the handshake needs its identity bytes.
    matching_advertisements: list[AdvertisementData] = []

    def is_lights(device: BLEDevice, advertisement: AdvertisementData) -> bool:
        """Whether this advertisement is the lights' own, remembering it when it is."""
        is_match = LIGHTS_NAME in (device.name, advertisement.local_name)
        if is_match:
            matching_advertisements.append(advertisement)
        return is_match

    device = await BleakScanner.find_device_by_filter(is_lights, timeout=SCAN_SECONDS)
    if device is None:
        raise LightsNotFoundError(f"'{LIGHTS_NAME}' not found in a {SCAN_SECONDS:.0f}s scan")
    identity = matching_advertisements[-1].manufacturer_data.get(MANUFACTURER_DATA_KEY, b"")
    return identity, device


def log_reply(_characteristic: object, reply: bytearray) -> None:
    """Log what the lights send back. Replies are not decoded yet; frames starting 56 are acks."""
    logger.info("reply %s", bytes(reply).hex(" "))
