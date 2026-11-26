"""Фінальне дотюнювання SA (LayoutOptimizerSA._polish): після нього жоден
swap і жоден 3-цикл рухомих клавіш не покращує розкладку."""
import itertools

from config.main_config import STATISTIC, geometry_config, load_moves
from core.layout_factory import build_layout
from core.mutator import LayoutOptimizerSA

MOVABLE = 6   # решту заморожуємо — щоб тест ішов секунди, а не хвилини


def _optimizer():
    name = "corne_42"
    layout = build_layout(geometry_config(name))
    letters = [k for k in layout.keys if k.char and len(k.char) == 1]
    for key in letters[MOVABLE:]:
        key.is_frozen = True
    config = {"seed": 1, "polish": True, "polish_cycles": True}
    return LayoutOptimizerSA(layout, STATISTIC, load_moves(name), config=config), layout


def test_polish_reaches_local_optimum():
    opt, layout = _optimizer()
    opt.best_layout = layout
    opt.best_score = start = opt._load(layout)
    opt._polish(layout)
    assert opt.best_score <= start
    assert opt.history[-1]["event"].startswith("polish")

    keys = opt._unfrozen(layout)
    assert len(keys) == MOVABLE
    base = opt._load(layout)
    assert abs(base - opt.best_score) <= 1e-9 * abs(base)
    for a, b in itertools.combinations(keys, 2):
        a.char, b.char = b.char, a.char
        assert opt.engine.try_layout(layout.keys) >= base
        a.char, b.char = b.char, a.char
    for a, b, c in itertools.combinations(keys, 3):
        old = (a.char, b.char, c.char)
        for chars in ((old[2], old[0], old[1]), (old[1], old[2], old[0])):
            a.char, b.char, c.char = chars
            assert opt.engine.try_layout(layout.keys) >= base
            a.char, b.char, c.char = old


def test_polish_keeps_frozen_keys():
    opt, layout = _optimizer()
    frozen = {k.position_id: k.char for k in layout.keys if k.is_frozen}
    opt.best_layout = layout
    opt.best_score = opt._load(layout)
    opt._polish(layout)
    assert {k.position_id: k.char for k in layout.keys if k.is_frozen} == frozen


def test_bad_run_arguments_keep_previous_best():
    """QA 2026-11-26: run_optimization з iterations < 1 або без рухомих клавіш
    перезаписував best_score/current_score до перевірки аргументів."""
    import copy

    import pytest

    opt, layout = _optimizer()
    opt.best_layout = copy.deepcopy(layout)
    opt.best_score = opt.current_score = -123.0   # «результат попереднього прогону»
    with pytest.raises(ValueError):
        opt.run_optimization(layout, iterations=0)
    frozen = copy.deepcopy(layout)
    for key in frozen.keys:
        key.is_frozen = True
    with pytest.raises(ValueError):
        opt.run_optimization(frozen, iterations=10)
    assert opt.best_score == opt.current_score == -123.0
