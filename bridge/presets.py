"""Saved looks ("presets"): six slots, each holding every panel's color plus the brightness.

They live in a JSON file in the user's config folder, so they survive clearing the browser.
server.py serves them to the page, and the page applies one by sending its panel colors and
brightness like any other control: the lights themselves store nothing. Colors are checked with
protocol.py's rules, so a saved preset is always one the lights can show.
"""

import json
import os
from pathlib import Path

import protocol

SLOT_COUNT = 6
# A preset as stored and served: {"panelColors": ["#rrggbb", one per panel], "brightness": 0-100}.
Preset = dict[str, object]
ALLOWED_SLOT_NUMBERS = range(1, SLOT_COUNT + 1)


def default_presets_path() -> Path:
    """Where presets are kept: $XDG_CONFIG_HOME, else ~/.config, per the XDG Base Directory spec."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config_home) / "haxagon-lights" / "presets.json"


def load_presets(path: Path) -> list[Preset | None]:
    """Read every slot, slot 1 first; None marks an empty slot. No file yet means all empty."""
    if not path.exists():
        return [None] * SLOT_COUNT
    return json.loads(path.read_text())["slots"]


def save_preset(path: Path, slot_number: int, preset: object) -> list[Preset | None]:
    """Check a preset and store it in slot 1-6, replacing what was there.

    Returns every slot after the save, as load_presets would. Only the known fields are stored.
    """
    protocol.require_within(slot_number, ALLOWED_SLOT_NUMBERS, "slot")
    checked = checked_preset(preset)
    slots = load_presets(path)
    slots[slot_number - 1] = checked
    write_presets(path, slots)
    return slots


def checked_preset(preset: object) -> Preset:
    """Raise ValueError unless the preset has one "#rrggbb" per panel and a brightness of 0-100."""
    if not isinstance(preset, dict):
        raise ValueError("a preset must be a JSON object")
    panel_colors = preset.get("panelColors")
    is_color_list = isinstance(panel_colors, list)
    if not is_color_list or len(panel_colors) != protocol.PANEL_COUNT:
        raise ValueError(f"panelColors must list {protocol.PANEL_COUNT} colors")
    for color in panel_colors:
        protocol.parse_hex_color(color)  # Raises on anything but "#rrggbb".
    brightness = preset.get("brightness")
    protocol.require_within(brightness, protocol.ALLOWED_PERCENTS, "brightness")
    return {"panelColors": panel_colors, "brightness": brightness}


def write_presets(path: Path, slots: list[Preset | None]) -> None:
    """Replace the file with these slots.

    Writes a temporary file and renames it over the old one, so a crash mid-write leaves the old
    presets whole instead of a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps({"slots": slots}, indent=2))
    temporary_path.replace(path)
