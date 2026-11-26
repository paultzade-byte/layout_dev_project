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


@pytest.mark.parametrize("meta", [["uk"], "uk", 5])
def test_stats_file_with_bad_meta_does_not_break_start(tmp_path, monkeypatch, meta):
    """QA 2026-11-26: meta не-об'єкт -> AttributeError у startup_statistic і меню «Статистика»."""
    import json
    from config import settings, stats_files
    from uiux import app as A
    bad = tmp_path / "ukr_bad.json"
    bad.write_text(json.dumps({**{k: {} for k in stats_files.NGRAM_KEYS}, "meta": meta}), encoding="utf-8")
    assert stats_files.read_meta(bad) is None and stats_files.language(bad) is None
    assert stats_files.load(bad)["unigrams"] == {}
    old = settings.load().get("statistic_file")
    try:
        settings.save(statistic_file=str(bad))
        statistic, path = A.startup_statistic()
        assert path in (None, bad)
    finally:
        settings.save(statistic_file=old)
    broken = tmp_path / "ukr_broken.json"
    broken.write_text(json.dumps({**{k: [] for k in stats_files.NGRAM_KEYS}, "meta": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        stats_files.load(broken)


def test_schema_requires_column_multiplier_other():
    """QA 2026-11-26: engine читає column_multiplier.other, а схема — ні -> сирий KeyError."""
    moves = load_moves("corne_42")
    del moves["base_effort"]["column_multiplier"]["other"]
    with pytest.raises(ValueError, match="column_multiplier.other"):
        validate_moves_config(moves)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 pytest.param(10**400, id="10**400")])
def test_schema_rejects_non_finite_weights(bad):
    """QA 2026-11-26: NaN / inf у вагах проходили validate_moves_config."""
    moves = load_moves("corne_42")
    moves["base_effort"]["row_multiplier"]["top"] = bad
    with pytest.raises(ValueError, match="row_multiplier.top"):
        validate_moves_config(moves)
    moves = load_moves("corne_42")
    moves["hand"]["left_mult"] = bad
    with pytest.raises(ValueError, match="left_mult"):
        validate_moves_config(moves)


@pytest.mark.parametrize("bad", [None, 5, "x"])
def test_build_layout_non_dict_position(bad):
    """QA 2026-11-26: null у positions -> AttributeError з обробника помилки замість ValueError."""
    geometry = geometry_config("corne_42")
    geometry = {**geometry, "positions": [*geometry["positions"], bad]}
    with pytest.raises(ValueError, match="invalid geometry position unknown"):
        build_layout(geometry)
