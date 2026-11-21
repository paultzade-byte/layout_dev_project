"""core/heat.py і MovementScoringEngine.per_char_penalty: теплові мапи."""

import pytest

from config.main_config import STATISTIC, geometry_config, load_moves
from core import heat
from core.layout_factory import build_layout
from core.scorer import MovementScoringEngine


@pytest.mark.parametrize("geo", ["corne_42", "generic_105_alpha"])
def test_per_char_penalty_sums_to_total(geo):
    layout = build_layout(geometry_config(geo))
    engine = MovementScoringEngine(layout.keys, load_moves(geo)).prepare_statistics(STATISTIC)
    total = engine.score().total_penalty
    assert sum(engine.per_char_penalty().values()) + engine._hand_run_const == pytest.approx(total, rel=1e-9)


@pytest.mark.parametrize("geo", ["corne_42", "generic_105_alpha"])
def test_maps_cover_letters_and_sum_to_100(geo):
    layout = build_layout(geometry_config(geo))
    engine = MovementScoringEngine(layout.keys, load_moves(geo)).prepare_statistics(STATISTIC)
    for values in (heat.frequency(layout.keys, STATISTIC), heat.discomfort(engine, layout.keys)):
        assert sum(values.values()) == pytest.approx(100.0)
        assert all(v >= 0 for v in values.values())
    freq = heat.frequency(layout.keys, STATISTIC)
    by_pos = {k.position_id: k.char for k in layout.keys}
    assert by_pos[max(freq, key=freq.get)] == "о"          # найчастіша літера української


def test_colors_ink_and_text():
    assert heat.heat_color(0.0) == heat.BLUE[0] and heat.heat_color(1.0) == heat.BLUE[-1]
    assert heat.heat_color(1.0, "pain") == heat.ORANGE[-1]
    assert heat.heat_ink(heat.BLUE[0]) == heat.INK_LIGHT   # темна заливка — світлий текст
    assert heat.heat_ink(heat.BLUE[-1]) == heat.INK_DARK
    cells = heat.cells({1: 10.0, 2: 0.01})
    assert cells[1]["fill"] == heat.BLUE[-1] and cells[2]["text"] == "<0.1"


def test_screenshot_with_heat(tmp_path):
    from uiux import render
    geo = "generic_105_alpha"
    g = geometry_config(geo)
    layout = build_layout(g)
    values = heat.frequency(layout.keys, STATISTIC)
    for name in ("m.png", "m.svg"):
        path = render.save(layout.keys, g, geo, tmp_path / name, "t", "", heat=heat.cells(values),
                           footer=heat.loads_text(layout.keys, values))
        assert path.stat().st_size > 1000
    assert "Ліва" in (tmp_path / "m.svg").read_text(encoding="utf-8")
