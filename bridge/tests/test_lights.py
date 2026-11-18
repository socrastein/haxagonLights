"""Checks lights.py's connection setup with a fake Bluetooth client, so no lights are needed.

The lights take one connection at a time, so a setup that fails must hand the link back, and a
scan that finds nothing must say what to do about it.
"""

import asyncio

import pytest

import lights
import protocol

FAKE_IDENTITY = bytes(range(6))


class FakeClient:
    """Stands in for BleakClient: records what is written and whether the link was closed."""

    def __init__(self, fails_to_subscribe: bool) -> None:
        self.fails_to_subscribe = fails_to_subscribe
        self.frames: list[bytes] = []
        self.disconnect_count = 0

    async def connect(self) -> None:
        """Pretend to open the link; the fake has no radio to open."""

    async def start_notify(self, _uuid: str, _callback: object) -> None:
        """Subscribe to replies, or fail the way a refused subscription would."""
        if self.fails_to_subscribe:
            raise RuntimeError("subscribe refused")

    async def write_gatt_char(self, _uuid: str, frame: bytes, response: bool) -> None:
        """Record the frame; the bridge always writes without response, as the app does."""
        assert response is False
        self.frames.append(frame)

    async def disconnect(self) -> None:
        """Count the close, so a test can see whether the link was handed back."""
        self.disconnect_count += 1


def use_fake_client(
    monkeypatch: pytest.MonkeyPatch, fails_to_subscribe: bool = False
) -> list[FakeClient]:
    """Replace the scan and the Bluetooth client; returns the list the created clients join."""
    created: list[FakeClient] = []

    def build_client(_device: object) -> FakeClient:
        client = FakeClient(fails_to_subscribe)
        created.append(client)
        return client

    async def find_fake_lights() -> tuple[bytes, object]:
        return FAKE_IDENTITY, object()  # The device is never used by the fake client.

    monkeypatch.setattr(lights, "BleakClient", build_client)
    monkeypatch.setattr(lights, "find_lights", find_fake_lights)
    return created


class TestConnectToLights:
    def test_a_successful_setup_keeps_the_link_and_sends_handshake_then_clock_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        created = use_fake_client(monkeypatch)
        connection = asyncio.run(lights.connect_to_lights())
        client = created[0]
        assert connection.client is client
        assert client.disconnect_count == 0
        assert [frame[1] for frame in client.frames] == [
            protocol.COMMAND_HANDSHAKE,
            protocol.COMMAND_CLOCK_SYNC,
        ]

    def test_a_failed_setup_closes_the_link_and_passes_the_error_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without this the link stays open with no connection stored, and the phone app is
        # locked out.
        created = use_fake_client(monkeypatch, fails_to_subscribe=True)
        with pytest.raises(RuntimeError, match="subscribe refused"):
            asyncio.run(lights.connect_to_lights())
        assert created[0].disconnect_count == 1


class TestFindLights:
    def test_a_scan_that_finds_nothing_says_what_to_do(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def scan_finds_nothing(_device_filter: object, timeout: float) -> None:
            """Stand-in for BleakScanner.find_device_by_filter: no lights answer."""
            assert timeout == lights.SCAN_SECONDS
            return None

        monkeypatch.setattr(lights.BleakScanner, "find_device_by_filter", scan_finds_nothing)
        with pytest.raises(lights.LightsNotFoundError, match="close the phone app"):
            asyncio.run(lights.find_lights())
