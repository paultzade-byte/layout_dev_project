import random

from config.main_config import geometry_config, load_moves
from core.layout_factory import build_layout
from core.scorer import UNSCORED_CHARS, MovementScoringEngine

TOLERANCE = 1e-9


def test_delta_matches_full_score(geometry_name, engines):
    """Те саме, що scripts/check_delta.py, коротше — для обох геометрій."""
    engine = engines(geometry_name)
    layout = build_layout(geometry_config(geometry_name))
    mutable = [k for k in layout.keys if k.char and len(k.char) == 1]
    rng = random.Random(7)
    engine.load(layout.keys)
    for _ in range(150):
        keys = rng.sample(mutable, rng.choice([2, 2, 3, 4]))
        old = [k.char for k in keys]
        for key, char in zip(keys, old[1:] + old[:1]):
            key.char = char
        delta = engine.try_layout(layout.keys)
        full = engine.update_layout(layout.keys).score().total_penalty
        assert abs(delta - full) / abs(full) < TOLERANCE
        if rng.random() < 0.4:
            engine.accept()
        else:
            for key, char in zip(keys, old):
                key.char = char


def test_enter_is_never_scored(statistic):
    """Enter не оцінюється навіть на розкладці і з будь-якою частотою."""
    assert "\n" in UNSCORED_CHARS
    layout = build_layout(geometry_config("corne_42"))
    free = next(k for k in layout.keys if not k.char)
    free.char, free.is_frozen = "\n", False
    moves = load_moves("corne_42")
    noisy = {name: dict(table) for name, table in statistic.items()}
    noisy["unigrams"]["\n"] = 1e12
    noisy["bigrams"]["а\n"] = 1e12
    noisy["trigrams"]["а\nо"] = 1e12
    noisy["skipgrams"]["\nо"] = 1e12

    base = MovementScoringEngine(layout.keys, moves).prepare_statistics(statistic).score()
    with_enter = MovementScoringEngine(layout.keys, moves).prepare_statistics(noisy).score()
    assert base.total_penalty == with_enter.total_penalty
