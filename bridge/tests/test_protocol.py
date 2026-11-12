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


class TestPerLightColors:
    """The 20-entry color table from the app's DIY screen, in snake order."""

    def test_panel_one_white_matches_the_first_capture(self) -> None:
        expected = frame("55 04 ff 42 01 ff ff ff") + bytes(57) + b"\x63"
        assert protocol.per_light_frame([(255, 255, 255)]) == expected

    def test_red_yellow_blue_matches_the_capture(self) -> None:
        expected = frame("55 04 ff 42 01 ff 00 00 ff ff 00 00 00 ff") + bytes(51) + b"\x63"
        panels = [(255, 0, 0), (255, 255, 0), (0, 0, 255)]
        assert protocol.per_light_frame(panels) == expected

    def test_always_sends_all_20_entries_because_shorter_frames_are_ignored(self) -> None:
        assert len(protocol.per_light_frame([(1, 2, 3)])) == 66

    def test_ends_with_the_constant_the_app_sends_not_a_checksum(self) -> None:
        assert protocol.per_light_frame([(1, 2, 3)])[-1] == 0x63
        assert protocol.per_light_frame([(9, 9, 9)])[-1] == 0x63

    def test_accepts_up_to_the_table_size_of_20(self) -> None:
        protocol.per_light_frame([(0, 0, 0)] * 20)
        with pytest.raises(ValueError):
            protocol.per_light_frame([(0, 0, 0)] * 21)

    def test_rejects_no_panels(self) -> None:
        with pytest.raises(ValueError):
            protocol.per_light_frame([])

    def test_channel_bound_is_255(self) -> None:
        protocol.per_light_frame([(255, 255, 255)])
        with pytest.raises(ValueError):
            protocol.per_light_frame([(256, 0, 0)])


class TestPanelColors:
    """The page's per-panel colors, sent as "#rrggbb" text."""

    def test_matches_the_per_light_frame_for_the_same_colors(self) -> None:
        expected = protocol.per_light_frame([(255, 0, 0), (255, 255, 0), (0, 0, 255)])
        assert protocol.panel_colors_frame(["#ff0000", "#ffff00", "#0000ff"]) == expected

    def test_accepts_up_to_the_table_size_of_20(self) -> None:
        protocol.panel_colors_frame(["#000000"] * 20)
        with pytest.raises(ValueError):
            protocol.panel_colors_frame(["#000000"] * 21)

    def test_rejects_a_color_that_is_not_hash_rrggbb(self) -> None:
        with pytest.raises(ValueError):
            protocol.panel_colors_frame(["#ff0000", "red"])

    def test_rejects_a_single_color_that_is_not_in_a_list(self) -> None:
        # A JSON string is iterable, so without this check "#ff0000" would be read as 7 colors.
        with pytest.raises(ValueError):
            protocol.panel_colors_frame("#ff0000")  # type: ignore[arg-type]


class TestGradient:
    """A fade along the snake from the start color to the end color."""

    PINK = "#ff95ff"
    BLUE = "#5bcefa"

    def table_of(self, gradient: bytes) -> list[tuple[int, int, int]]:
        """Read a frame's 20 table entries back as colors."""
        table = gradient[5:65]
        return [tuple(table[i : i + 3]) for i in range(0, 60, 3)]  # type: ignore[misc]

    def test_first_panel_is_the_start_color(self) -> None:
        assert self.table_of(protocol.gradient_frame(self.PINK, self.BLUE))[0] == (255, 149, 255)

    def test_twelfth_panel_the_tip_is_the_end_color(self) -> None:
        assert self.table_of(protocol.gradient_frame(self.PINK, self.BLUE))[11] == (91, 206, 250)

    def test_panels_are_evenly_spaced_in_eleven_steps(self) -> None:
        # 12 panels make 11 steps, so a channel going 0 to 110 rises by 10 per panel.
        fourth = self.table_of(protocol.gradient_frame("#000000", "#6e006e"))[3]
        assert fourth == (30, 0, 30)

    def test_entries_past_the_last_panel_stay_dark(self) -> None:
        unused = self.table_of(protocol.gradient_frame(self.PINK, self.BLUE))[12:]
        assert unused == [(0, 0, 0)] * 8

    def test_a_single_color_gradient_is_flat(self) -> None:
        panels = self.table_of(protocol.gradient_frame(self.PINK, self.PINK))[:12]
        assert set(panels) == {(255, 149, 255)}

    @pytest.mark.parametrize("bad", ["ff95ff", "#ff95f", "#ff95ffff", "#gg95ff", "pink", ""])
    def test_rejects_colors_that_are_not_hash_rrggbb(self, bad: str) -> None:
        with pytest.raises(ValueError):
            protocol.gradient_frame(bad, self.BLUE)

    def test_rejects_a_color_that_is_not_text(self) -> None:
        with pytest.raises(ValueError):
            protocol.gradient_frame(123456, self.BLUE)  # type: ignore[arg-type]


class TestBlending:
    """Mixing two colors in RGB."""

    def test_needs_at_least_two_steps(self) -> None:
        with pytest.raises(ValueError):
            protocol.blend_colors((0, 0, 0), (255, 255, 255), 1)

    def test_two_steps_are_just_the_ends(self) -> None:
        assert protocol.blend_colors((1, 2, 3), (4, 5, 6), 2) == [(1, 2, 3), (4, 5, 6)]
