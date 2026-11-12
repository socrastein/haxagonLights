"""Checks protocol.py against frames captured from the MeRGBW app on 2026-11-11.

Each expected value is a real frame the app wrote to the lights, so a passing test means the bridge
produces exactly what the app would have sent.
"""

from datetime import datetime

import pytest

import protocol


def frame(hex_text: str) -> bytes:
    """Turn captured bytes written as '55 01 ff 06 00 a4' into bytes."""
    return bytes.fromhex(hex_text)


class TestFraming:
    """The shared envelope: start byte, command, address, total length, checksum."""

    def test_length_byte_counts_the_whole_frame(self) -> None:
        assert protocol.build_frame(0x01, b"\x00")[3] == 6

    def test_state_query_has_an_empty_payload(self) -> None:
        assert protocol.state_query_frame() == frame("55 00 ff 05 a6")

    def test_checksum_wraps_to_one_byte(self) -> None:
        wrapped_frame = protocol.build_frame(0x03, bytes([0, 0xF0, 0x03, 0xE8]))
        assert wrapped_frame[-1] == 0xC4


class TestPower:
    """Power on and off."""

    def test_off(self) -> None:
        assert protocol.power_frame(False) == frame("55 01 ff 06 00 a4")

    def test_on(self) -> None:
        assert protocol.power_frame(True) == frame("55 01 ff 06 01 a3")


class TestColor:
    """Hue and saturation, with brightness kept separate."""

    def test_red(self) -> None:
        assert protocol.color_frame(0, 100) == frame("55 03 ff 09 00 00 03 e8 b4")

    def test_green(self) -> None:
        assert protocol.color_frame(120, 100) == frame("55 03 ff 09 00 78 03 e8 3c")

    def test_blue(self) -> None:
        assert protocol.color_frame(240, 100) == frame("55 03 ff 09 00 f0 03 e8 c4")

    def test_white_is_zero_saturation(self) -> None:
        assert protocol.color_frame(0, 0) == frame("55 03 ff 09 00 00 00 00 9f")

    def test_hue_above_255_uses_both_bytes(self) -> None:
        hue_payload = protocol.color_frame(300, 100)[4:6]
        assert hue_payload == bytes([0x01, 0x2C])

    def test_hue_bound_is_360_degrees(self) -> None:
        protocol.color_frame(360, 100)
        with pytest.raises(ValueError):
            protocol.color_frame(361, 100)

    def test_saturation_bound_is_100_percent(self) -> None:
        with pytest.raises(ValueError):
            protocol.color_frame(0, 101)


class TestBrightness:
    """Brightness is 0-100 percent for callers and 0-1000 on the wire."""

    def test_full_brightness(self) -> None:
        assert protocol.brightness_frame(100) == frame("55 05 ff 07 03 e8 b4")

    def test_zero_brightness(self) -> None:
        assert protocol.brightness_frame(0) == frame("55 05 ff 07 00 00 9f")

    def test_rejects_values_over_100(self) -> None:
        with pytest.raises(ValueError):
            protocol.brightness_frame(101)

    def test_rejects_booleans_posing_as_numbers(self) -> None:
        with pytest.raises(ValueError):
            protocol.brightness_frame(True)


class TestScenes:
    """Scene selection and the inverted speed scale."""

    def test_symphony(self) -> None:
        assert protocol.scene_frame("symphony") == frame("55 06 ff 07 00 02 9c")

    def test_melody_is_the_last_scene_in_the_capture(self) -> None:
        assert protocol.scene_frame("melody") == frame("55 06 ff 07 00 20 7e")

    def test_every_captured_scene_id_is_known(self) -> None:
        captured_ids = {2, 3, 4, 7, 0x10, 0x17, 0x2D, 0x23, 0x37, 0x0D, 0x30, 0x47, 0x5B, 0x6D,
                        0x71, 0x3B, 0x1A, 0x20}
        assert set(protocol.SCENE_IDS.values()) == captured_ids

    def test_unknown_scene_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            protocol.scene_frame("disco")

    def test_app_speed_100_is_wire_0(self) -> None:
        assert protocol.scene_speed_frame(100) == frame("55 0f ff 06 00 96")

    def test_app_speed_31_is_wire_69(self) -> None:
        assert protocol.scene_speed_frame(31) == frame("55 0f ff 06 45 51")

    def test_app_speed_0_is_wire_100(self) -> None:
        assert protocol.scene_speed_frame(0) == frame("55 0f ff 06 64 32")


class TestMusic:
    """Music modes and sensitivity."""

    def test_spectrum_1(self) -> None:
        assert protocol.music_mode_frame("spectrum 1") == frame("55 07 ff 06 02 9c")

    def test_rhythm_is_the_last_mode_in_the_capture(self) -> None:
        assert protocol.music_mode_frame("rhythm") == frame("55 07 ff 06 04 9a")

    def test_full_sensitivity_is_sent_as_is(self) -> None:
        assert protocol.music_sensitivity_frame(100) == frame("55 08 ff 06 64 39")

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            protocol.music_mode_frame("techno")


class TestConnectionSetup:
    """The handshake and clock sync the app sends right after connecting."""

    def test_handshake_echoes_the_advertisement_identity(self) -> None:
        advertisement = frame("65 a6 14 2f 58 15 00 00 01 54 47 36 30 39")
        assert protocol.handshake_frame(advertisement) == frame("55 0e ff 0b 65 a6 14 2f 58 15 d7")

    def test_clock_sync_on_a_wednesday(self) -> None:
        wednesday = datetime(2026, 11, 11, 15, 48, 6)
        captured = frame("55 0c ff 0d 07 ea 0b 0b 0f 30 06 03 43")
        assert protocol.clock_sync_frame(wednesday) == captured
