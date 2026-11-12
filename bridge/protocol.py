"""The byte format the Haxagon lights understand, as pure functions from intent to frames.

Nothing here touches Bluetooth: lights.py sends the frames, server.py decides which one to build.
Every number below was decoded from a Bluetooth capture of the MeRGBW app on 2026-11-11, not from
documentation, so each table says what was observed.

A frame is: 0x55, command, 0xFF, total length, payload bytes..., checksum.
"""

from datetime import datetime

Rgb = tuple[int, int, int]  # Red, green, blue, each 0-255.

FRAME_START = 0x55
FRAME_ADDRESS = 0xFF  # Always 0xFF in every captured frame.
FRAME_OVERHEAD_BYTES = 5  # Start, command, address, length and checksum around the payload.
BYTE_MASK = 0xFF
BYTE_MAXIMUM = 255  # Largest value one color channel can hold.

COMMAND_STATE_QUERY = 0x00
COMMAND_POWER = 0x01
COMMAND_COLOR = 0x03
COMMAND_BRIGHTNESS = 0x05
COMMAND_SCENE = 0x06
COMMAND_MUSIC_MODE = 0x07
COMMAND_MUSIC_SENSITIVITY = 0x08
COMMAND_CLOCK_SYNC = 0x0C
COMMAND_HANDSHAKE = 0x0E
COMMAND_SCENE_SPEED = 0x0F
COMMAND_PER_LIGHT_COLORS = 0x04

# The lights report hue in degrees and saturation and brightness on a 0-1000 scale.
MAXIMUM_HUE_DEGREES = 360
WIRE_SCALE_MAXIMUM = 1000
MAXIMUM_PERCENT = 100
# Whole numbers a caller may pass, as ranges (a range's end is exclusive, hence the + 1).
ALLOWED_HUE_DEGREES = range(0, MAXIMUM_HUE_DEGREES + 1)
ALLOWED_PERCENTS = range(0, MAXIMUM_PERCENT + 1)
ALLOWED_CHANNEL_VALUES = range(0, BYTE_MAXIMUM + 1)
BLACK: Rgb = (0, 0, 0)
HEX_COLOR_LENGTH = len("#rrggbb")
PERCENT_TO_WIRE_SCALE = WIRE_SCALE_MAXIMUM // MAXIMUM_PERCENT

# How many leading bytes of the lights' Bluetooth advertisement identify them in the handshake.
HANDSHAKE_IDENTITY_LENGTH = 6

# The per-light ("DIY") command carries a table of 20 RGB entries. The panels are one chain of
# addressable LEDs, so entry N lights the Nth panel along the chain from the cable. Entries past
# the last panel do nothing, but the lights ignore a frame unless it has all 20.
# A panel plugged into two neighbors gets the same data twice: with the last panel also plugged
# into the first, it copied panel 2 until that connector was removed.
PER_LIGHT_TABLE_ENTRIES = 20
PANEL_COUNT = 12  # The one set this was tried on.
PER_LIGHT_MODE_FLAG = 0x01  # First payload byte in every capture; 0x00 and 0x02 were ignored.
# This command ends in a constant instead of a checksum. Every capture had 0x63; the lights
# accepted 0x00 as well, so it is probably not checked. We send what the app sends.
PER_LIGHT_TRAILER = 0x63

# Scene name to the ID the app sends, in the order the app lists them.
SCENE_IDS = {
    "symphony": 0x02,
    "energy": 0x03,
    "jump": 0x04,
    "vitality": 0x07,
    "accumulation": 0x10,
    "chase": 0x17,
    "space-time": 0x2D,
    "ephemeral": 0x23,
    "flow": 0x37,
    "forest": 0x0D,
    "neon lights": 0x30,
    "green jade": 0x47,
    "running": 0x5B,
    "pink light": 0x6D,
    "alarm": 0x71,
    "aurora": 0x3B,
    "rainbow": 0x1A,
    "melody": 0x20,
}

# Music mode name to the ID the app sends, in the order the app lists them.
MUSIC_MODE_IDS = {
    "spectrum 1": 0x02,
    "spectrum 2": 0x05,
    "spectrum 3": 0x06,
    "flowing": 0x03,
    "rolling": 0x01,
    "rhythm": 0x04,
}


def build_frame(command: int, payload: bytes) -> bytes:
    """Wrap a payload in the start byte, command, address, length and checksum.

    The length byte counts the whole frame. The checksum is the bitwise complement of the sum of
    every earlier byte, which matches all captured frames (e.g. power off is 55 01 ff 06 00 a4).
    """
    total_length = len(payload) + FRAME_OVERHEAD_BYTES
    unchecked = bytes([FRAME_START, command, FRAME_ADDRESS, total_length]) + payload
    return unchecked + bytes([checksum_of(unchecked)])


def checksum_of(unchecked_frame: bytes) -> int:
    """Return the complement of the byte sum, kept to one byte."""
    return ~sum(unchecked_frame) & BYTE_MASK


def power_frame(is_on: bool) -> bytes:
    """Turn the lights on (True) or off (False)."""
    return build_frame(COMMAND_POWER, bytes([1 if is_on else 0]))


def color_frame(hue_degrees: int, saturation_percent: int) -> bytes:
    """Show a solid color: hue 0 is red, 120 green, 240 blue; saturation 0 is white.

    The payload is hue then saturation, two bytes each: green at full saturation was captured as
    00 78 03 e8. Brightness is a separate command (brightness_frame), as in the app.
    """
    require_within(hue_degrees, ALLOWED_HUE_DEGREES, "hue")
    require_within(saturation_percent, ALLOWED_PERCENTS, "saturation")
    saturation_on_wire = saturation_percent * PERCENT_TO_WIRE_SCALE
    return build_frame(COMMAND_COLOR, two_bytes(hue_degrees) + two_bytes(saturation_on_wire))


def two_bytes(value: int) -> bytes:
    """Encode a number as two bytes, most significant first (0x03E8 becomes 03 e8)."""
    return value.to_bytes(2, "big")


def brightness_frame(brightness_percent: int) -> bytes:
    """Set brightness from 0 to 100 percent (full is 03 e8 on the wire)."""
    require_within(brightness_percent, ALLOWED_PERCENTS, "brightness")
    return build_frame(COMMAND_BRIGHTNESS, two_bytes(brightness_percent * PERCENT_TO_WIRE_SCALE))


def scene_frame(scene_name: str) -> bytes:
    """Start a built-in scene by name (see SCENE_IDS)."""
    require_known(scene_name, SCENE_IDS, "scene")
    return build_frame(COMMAND_SCENE, bytes([0, SCENE_IDS[scene_name]]))


def scene_speed_frame(speed_percent: int) -> bytes:
    """Set how fast the current scene runs, as the app shows it (100 is fastest).

    The lights want the opposite scale: the app's speed 31 was captured as 0x45 (69), speed 0 as
    0x64 (100) and speed 100 as 0x00. So the wire value is 100 minus the displayed speed.
    """
    require_within(speed_percent, ALLOWED_PERCENTS, "speed")
    return build_frame(COMMAND_SCENE_SPEED, bytes([MAXIMUM_PERCENT - speed_percent]))


def music_mode_frame(mode_name: str) -> bytes:
    """Switch to a microphone-driven music mode by name (see MUSIC_MODE_IDS)."""
    require_known(mode_name, MUSIC_MODE_IDS, "music mode")
    return build_frame(COMMAND_MUSIC_MODE, bytes([MUSIC_MODE_IDS[mode_name]]))


def music_sensitivity_frame(sensitivity_percent: int) -> bytes:
    """Set how strongly music modes react, 0 to 100 (sent as-is, unlike scene speed)."""
    require_within(sensitivity_percent, ALLOWED_PERCENTS, "sensitivity")
    return build_frame(COMMAND_MUSIC_SENSITIVITY, bytes([sensitivity_percent]))


def handshake_frame(advertisement_bytes: bytes) -> bytes:
    """Greet the lights with the first 6 bytes of their own advertisement.

    The app sends this right after connecting and the lights answer 56 0e ff 06 01 95. Whether
    the lights refuse commands without it is not yet known, so the bridge sends it like the app.
    """
    return build_frame(COMMAND_HANDSHAKE, advertisement_bytes[:HANDSHAKE_IDENTITY_LENGTH])


def clock_sync_frame(now: datetime) -> bytes:
    """Tell the lights the current time: year (2 bytes), month, day, hour, minute, second, weekday.

    Weekday is 1 for Monday through 7 for Sunday: the capture was a Wednesday and sent 3. Sunday
    is unverified.
    """
    date_and_time = bytes([now.month, now.day, now.hour, now.minute, now.second, now.isoweekday()])
    return build_frame(COMMAND_CLOCK_SYNC, two_bytes(now.year) + date_and_time)


def state_query_frame() -> bytes:
    """Ask the lights for their state; they answer with a 56 00 ff 14 ... notification."""
    return build_frame(COMMAND_STATE_QUERY, b"")


def per_light_frame(panel_colors: list[Rgb]) -> bytes:
    """Color each panel separately: one (red, green, blue) per panel, in snake order.

    Give 1 to 20 colors, the table's size; the rest of the table is filled with black. Captured
    example: red, yellow, blue then nothing is 55 04 ff 42 01 ff0000 ffff00 0000ff 00... 63.
    """
    if not 1 <= len(panel_colors) <= PER_LIGHT_TABLE_ENTRIES:
        raise ValueError(f"give 1 to {PER_LIGHT_TABLE_ENTRIES} panel colors")
    unused_entries = [BLACK] * (PER_LIGHT_TABLE_ENTRIES - len(panel_colors))
    table = b"".join(color_bytes(color) for color in panel_colors + unused_entries)
    frame = build_frame(COMMAND_PER_LIGHT_COLORS, bytes([PER_LIGHT_MODE_FLAG]) + table)
    return frame[:-1] + bytes([PER_LIGHT_TRAILER])  # Replace the checksum: see PER_LIGHT_TRAILER.


def gradient_frame(start_color: str, end_color: str) -> bytes:
    """Fade along the chain from the start color on panel 1 to the end color on the last panel.

    Colors are hex like "#ff95ff".
    """
    start = parse_hex_color(start_color)
    end = parse_hex_color(end_color)
    return per_light_frame(blend_colors(start, end, PANEL_COUNT))


def blend_colors(start: Rgb, end: Rgb, steps: int) -> list[Rgb]:
    """Return steps colors from start to end inclusive, evenly spaced in RGB.

    RGB mixing matches how a CSS linear-gradient between two colors looks on screen.
    """
    if steps < 2:
        raise ValueError("a blend needs at least 2 steps")
    last_step = steps - 1
    return [blend_color(start, end, step / last_step) for step in range(steps)]


def blend_color(start: Rgb, end: Rgb, fraction: float) -> Rgb:
    """Mix two colors: fraction 0 is the start, 1 is the end, 0.5 is halfway."""
    (start_red, start_green, start_blue), (end_red, end_green, end_blue) = start, end
    return (
        mix_channel(start_red, end_red, fraction),
        mix_channel(start_green, end_green, fraction),
        mix_channel(start_blue, end_blue, fraction),
    )


def mix_channel(start: int, end: int, fraction: float) -> int:
    """Move from start toward end by the fraction, rounded to a whole channel value."""
    return round(start + (end - start) * fraction)


def parse_hex_color(hex_color: str) -> Rgb:
    """Read "#rrggbb" (what a browser color picker gives) as (red, green, blue), each 0-255."""
    is_well_formed = isinstance(hex_color, str) and len(hex_color) == HEX_COLOR_LENGTH
    if not is_well_formed or not hex_color.startswith("#"):
        raise ValueError(f"color must look like #rrggbb, not {hex_color!r}")
    channels = bytes.fromhex(hex_color[1:])  # Raises ValueError itself on non-hex digits.
    return channels[0], channels[1], channels[2]


def color_bytes(color: Rgb) -> bytes:
    """Encode one (red, green, blue) as three bytes, refusing channels outside 0-255."""
    for channel in color:
        require_within(channel, ALLOWED_CHANNEL_VALUES, "color channel")
    return bytes(color)


def require_within(value: int, allowed: range, label: str) -> None:
    """Raise ValueError unless the value is a whole number in the allowed range.

    Booleans are refused even though Python counts True as 1, because a JSON true sent as a
    brightness is a mistake in the page, not a request for 1.
    """
    is_whole_number = isinstance(value, int) and not isinstance(value, bool)
    if not is_whole_number or value not in allowed:
        raise ValueError(f"{label} must be a whole number from {allowed[0]} to {allowed[-1]}")


def require_known(name: str, known_names: dict[str, int], label: str) -> None:
    """Raise ValueError unless the name is one of the table's keys."""
    if name not in known_names:
        raise ValueError(f"unknown {label} '{name}'")
