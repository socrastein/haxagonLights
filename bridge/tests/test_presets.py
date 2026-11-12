"""Checks presets.py: six slots of panel colors and brightness, kept in a JSON file."""

from pathlib import Path

import pytest

import presets

PINK = "#ff95ff"


def a_preset(brightness: int = 80) -> dict[str, object]:
    """A valid preset: every panel pink at the given brightness."""
    return {"panelColors": [PINK] * 12, "brightness": brightness}


@pytest.fixture
def presets_path(tmp_path: Path) -> Path:
    """A presets file in a folder that does not exist yet, as on first use."""
    return tmp_path / "config" / "haxagon-lights" / "presets.json"


class TestLoad:
    def test_no_file_yet_means_six_empty_slots(self, presets_path: Path) -> None:
        assert presets.load_presets(presets_path) == [None] * 6


class TestSave:
    def test_a_saved_preset_loads_back_in_its_slot(self, presets_path: Path) -> None:
        presets.save_preset(presets_path, 3, a_preset())
        assert presets.load_presets(presets_path) == [None, None, a_preset(), None, None, None]

    def test_returns_every_slot_after_the_save(self, presets_path: Path) -> None:
        slots = presets.save_preset(presets_path, 1, a_preset())
        assert slots == presets.load_presets(presets_path)

    def test_saving_again_replaces_only_that_slot(self, presets_path: Path) -> None:
        presets.save_preset(presets_path, 1, a_preset(10))
        presets.save_preset(presets_path, 2, a_preset(20))
        presets.save_preset(presets_path, 1, a_preset(30))
        slots = presets.load_presets(presets_path)
        assert [slots[0], slots[1]] == [a_preset(30), a_preset(20)]

    def test_drops_fields_it_does_not_know(self, presets_path: Path) -> None:
        slots = presets.save_preset(presets_path, 1, {**a_preset(), "extra": "ignored"})
        assert slots[0] == a_preset()

    def test_leaves_no_temporary_file_behind(self, presets_path: Path) -> None:
        presets.save_preset(presets_path, 1, a_preset())
        assert [path.name for path in presets_path.parent.iterdir()] == ["presets.json"]

    @pytest.mark.parametrize("slot_number", [1, 6])
    def test_accepts_slots_1_and_6(self, presets_path: Path, slot_number: int) -> None:
        presets.save_preset(presets_path, slot_number, a_preset())

    @pytest.mark.parametrize("slot_number", [0, 7])
    def test_refuses_slots_outside_1_to_6(self, presets_path: Path, slot_number: int) -> None:
        with pytest.raises(ValueError):
            presets.save_preset(presets_path, slot_number, a_preset())


class TestCheckedPreset:
    def test_refuses_something_that_is_not_an_object(self) -> None:
        with pytest.raises(ValueError):
            presets.checked_preset([PINK] * 12)

    @pytest.mark.parametrize("count", [11, 13])
    def test_needs_exactly_one_color_per_panel(self, count: int) -> None:
        with pytest.raises(ValueError):
            presets.checked_preset({"panelColors": [PINK] * count, "brightness": 50})

    def test_refuses_a_color_that_is_not_hash_rrggbb(self) -> None:
        with pytest.raises(ValueError):
            presets.checked_preset({"panelColors": ["pink"] + [PINK] * 11, "brightness": 50})

    @pytest.mark.parametrize("brightness", [0, 100])
    def test_accepts_brightness_0_and_100(self, brightness: int) -> None:
        presets.checked_preset(a_preset(brightness))

    @pytest.mark.parametrize("brightness", [-1, 101, True, "50", None])
    def test_refuses_brightness_outside_0_to_100(self, brightness: object) -> None:
        with pytest.raises(ValueError):
            presets.checked_preset({"panelColors": [PINK] * 12, "brightness": brightness})


class TestDefaultPath:
    def test_follows_xdg_config_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert presets.default_presets_path() == tmp_path / "haxagon-lights" / "presets.json"

    def test_falls_back_to_dot_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        expected = Path.home() / ".config" / "haxagon-lights" / "presets.json"
        assert presets.default_presets_path() == expected
