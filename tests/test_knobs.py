"""Повзунки впливу (core/knobs.py) і штраф близькості до ЙЦУКЕН."""
import random

from config.main_config import geometry_config, load_moves, start_layout
from core import knobs
from core.layout_factory import build_layout
from core.scorer import MovementScoringEngine

GEO = "generic_105_alpha"


def test_steps_and_factors():
    assert [knobs.step(v) for v in (-2, -1.6, -0.49, 0.5, 1.4, 1.51, 9)] == [-2, -2, 0, 0, 1, 2, 2]
    assert knobs.factor(0) == 1.0 and knobs.factor(2) == 2.0 and knobs.factor(-2) == 0.5


def test_neutral_knobs_keep_weights(geometry_name):
    moves = load_moves(geometry_name)
    values = {k.id: 0.3 for k in knobs.KNOBS}  # у діапазоні кроку 0
    assert knobs.apply(moves, values, geometry_config(geometry_name)) == moves


def test_knob_moves_its_weights():
    moves = load_moves(GEO)
    out = knobs.apply(moves, {"vertical": 2, "pinky": -2})
    assert out["same_finger"]["vertical"] == moves["same_finger"]["vertical"] * 2
    assert abs(out["finger_load"]["cap"]["pinky"] - moves["finger_load"]["cap"]["pinky"] * 2) < 1e-12
    assert out["same_finger"]["lateral"] == moves["same_finger"]["lateral"]
    # у ваг спліта нема bottom_left / closeness — просто пропускаються
    knobs.apply(load_moves("corne_42"), {"home_row": 2, "closeness": 2})


def test_closeness_off_is_bit_identical(statistic):
    geo = geometry_config(GEO)
    layout = start_layout(GEO)
    moves = load_moves(GEO)
    off = MovementScoringEngine(layout.keys, moves).prepare_statistics(statistic).score()
    on_zero = knobs.apply(moves, {}, geo, closeness=False)
    again = MovementScoringEngine(layout.keys, on_zero).prepare_statistics(statistic).score()
    assert off.total_penalty == again.total_penalty and off.closeness_penalty == 0.0


def test_closeness_penalty_and_delta(statistic):
    geo = geometry_config(GEO)
    moves = knobs.apply(load_moves(GEO), {"closeness": 0}, geo, closeness=True)
    ycuken = build_layout(geo)
    engine = MovementScoringEngine(ycuken.keys, moves).prepare_statistics(statistic)
    assert engine.score().closeness_penalty == 0.0          # ЙЦУКЕН — сам собі
    assert engine.update_layout(start_layout(GEO).keys).score().closeness_penalty > 0
    # delta == повний score з увімкненою близькістю
    layout = start_layout(GEO)
    mutable = [k for k in layout.keys if k.char and len(k.char) == 1]
    rng = random.Random(3)
    engine.load(layout.keys)
    for _ in range(60):
        keys = rng.sample(mutable, 2)
        keys[0].char, keys[1].char = keys[1].char, keys[0].char
        delta = engine.try_layout(layout.keys)
        full = engine.update_layout(layout.keys).score().total_penalty
        assert abs(delta - full) / full < 1e-9
        engine.accept()


def test_closeness_metrics(statistic):
    geo = geometry_config(GEO)
    c = knobs.closeness_metrics(build_layout(geo).keys, geo, statistic)
    assert c["in_place"] == c["of"] and abs(c["share"] - 100) < 1e-9


def test_presets_match_by_steps():
    from core import knobs
    std, split = "generic_105_alpha", "corne_42"
    assert knobs.matching_preset({"values": {}, "closeness": False}, std) == "Рекомендовано"
    # близькість вимкнена — її повзунок не діє, крок 0.3 ≈ 0
    assert knobs.matching_preset({"values": {"closeness": 2, "home_row": 0.3}}, std) == "Рекомендовано"
    assert knobs.matching_preset({"values": {"pinky": 1.8, "home_row": 1.2}}, split) == "Бережу мізинці"
    assert knobs.matching_preset({"values": {"closeness": 2}, "closeness": True}, std) == "Мінімум змін від ЙЦУКЕН"
    # на спліті пресету близькості нема, а прапорець там не діє
    assert "Мінімум змін від ЙЦУКЕН" not in [p.title for p in knobs.presets_for(split)]
    assert knobs.matching_preset({"values": {"pinky": 1}}, std) is None
    mine = {"мій": {"values": {"pinky": 1}, "closeness": False}}
    assert knobs.matching_preset({"values": {"pinky": 0.9}}, std, mine) == "мій"
    for p in knobs.PRESETS:   # усі id пресетів — справжні повзунки
        assert all(k in knobs.KNOBS_BY_ID for k, _ in p.values)
