import pytest

from config import paths
from config.main_config import GEOMETRIES, MOVES_FILES, geometry_config, load_moves
from core.layout_factory import build_layout
from core.scorer import validate_moves_config


def test_every_geometry_has_weights():
    assert set(GEOMETRIES) <= set(MOVES_FILES)


def test_weights_validate(geometry_name):
    validate_moves_config(load_moves(geometry_name))


def test_load_moves_returns_fresh_copy():
    a = load_moves("corne_42")
    a["hand"]["left_mult"] = 999
    assert load_moves("corne_42")["hand"]["left_mult"] != 999


def test_unknown_geometry():
    with pytest.raises(KeyError):
        geometry_config("nope")


def test_build_layout(geometry_name):
    layout = build_layout(geometry_config(geometry_name))
    ids = [k.position_id for k in layout.keys]
    assert len(ids) == len(set(ids))
    letters = [k.char for k in layout.keys if len(k.char) == 1]
    assert len(letters) == len(set(letters)), "одна літера на двох клавішах"


def test_user_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYOUT_USER_DIR", str(tmp_path / "u"))
    assert paths.user_data_dir() == tmp_path / "u"


def test_layouts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.layouts_dir() == tmp_path / "ukr-layout"          # немає Documents
    (tmp_path / "Documents").mkdir()
    assert paths.layouts_dir() == tmp_path / "Documents" / "ukr-layout"


def test_settings_roundtrip_and_bad_file():
    from config import settings
    from config.main_config import GEOMETRIES
    settings.save(mode="generic_105_alpha")
    assert settings.initial_mode(GEOMETRIES) == "generic_105_alpha"
    settings._path().write_text("{not json", encoding="utf-8")
    assert settings.load() == {}
    assert settings.initial_mode(GEOMETRIES) in GEOMETRIES
    settings.save(mode=None)


def test_start_layout_keeps_char_set(geometry_name):
    from config.main_config import geometry_config, start_layout
    from core.layout_factory import build_layout
    chars = sorted(k.char for k in start_layout(geometry_name).keys)
    assert chars == sorted(k.char for k in build_layout(geometry_config(geometry_name)).keys)
