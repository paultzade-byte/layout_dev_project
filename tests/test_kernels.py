"""Ядра numba (core/kernels.py) дають ту саму delta-оцінку, що й NumPy-шлях."""
import random

import pytest

from config.main_config import STATISTIC, geometry_config, load_moves
from core import kernels, scorer
from core.layout_factory import build_layout

pytestmark = pytest.mark.skipif(not kernels.AVAILABLE, reason="numba не встановлена")


def test_kernels_match_numpy(geometry_name, monkeypatch):
    layout = build_layout(geometry_config(geometry_name))
    engine = scorer.MovementScoringEngine(layout.keys, load_moves(geometry_name)).prepare_statistics(STATISTIC)
    keys = [k for k in layout.keys if k.char and len(k.char) == 1]
    rng = random.Random(5)
    engine.load(layout.keys)
    for _ in range(200):
        group = rng.sample(keys, rng.choice([2, 2, 3, 4]))
        old = [k.char for k in group]
        for key, char in zip(group, old[1:] + old[:1]):
            key.char = char
        monkeypatch.setattr(scorer, "USE_KERNELS", False)
        expected = engine.try_layout(layout.keys)
        monkeypatch.setattr(scorer, "USE_KERNELS", True)
        got = engine.try_layout(layout.keys)
        assert got == pytest.approx(expected, rel=1e-12)
        if rng.random() < 0.4:
            engine.accept()          # pending — від ядер
        else:
            for key, char in zip(group, old):
                key.char = char
    full = engine.update_layout(layout.keys).score().total_penalty
    assert engine.load(layout.keys) == pytest.approx(full, rel=1e-12)
    assert scorer.USE_KERNELS      # ядра не вимкнулись через помилку
