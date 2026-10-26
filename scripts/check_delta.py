"""Перевірка delta-оцінки: engine.try_layout() має збігатися з повним
score() на випадковому блуканні (swap, 3-цикли, подвійні swap, accept).

Запускати після будь-якої зміни моделі оцінки (core/scorer.py, moves.yaml):
    python scripts/check_delta.py [КРОКІВ]
Друкує максимальне відносне розходження; очікувано ~1e-15.
"""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC
from core.layout_factory import build_layout
from core.scorer import MovementScoringEngine

TOLERANCE = 1e-9


def main():
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    rng = random.Random(7)
    layout = build_layout(GEOMETRY_CONFIG)
    engine = MovementScoringEngine(layout.keys, MOVES_CONFIG).prepare_statistics(STATISTIC)
    mutable = [k for k in layout.keys if k.char and len(k.char) == 1]

    engine.load(layout.keys)
    worst = 0.0
    try_time = full_time = 0.0
    for _ in range(steps):
        keys = rng.sample(mutable, rng.choice([2, 2, 2, 3, 4]))
        old_chars = [k.char for k in keys]
        new_chars = old_chars[1:] + old_chars[:1]
        for key, char in zip(keys, new_chars):
            key.char = char

        started = time.perf_counter()
        delta_total = engine.try_layout(layout.keys)
        try_time += time.perf_counter() - started
        started = time.perf_counter()
        full_total = engine.update_layout(layout.keys).score().total_penalty
        full_time += time.perf_counter() - started
        worst = max(worst, abs(delta_total - full_total) / abs(full_total))

        if rng.random() < 0.4:
            engine.accept()
        else:
            for key, char in zip(keys, old_chars):
                key.char = char

    reload_diff = abs(engine.load(layout.keys) - engine.score().total_penalty) / engine.score().total_penalty
    print(f"{steps} кроків: max rel diff try_layout vs score() {worst:.1e}, load() vs score() {reload_diff:.1e}")
    print(f"try_layout {try_time / steps * 1e3:.3f} ms, score() {full_time / steps * 1e3:.3f} ms")
    if worst > TOLERANCE or reload_diff > TOLERANCE:
        sys.exit("FAIL: delta-оцінка розходиться з повним score()")


if __name__ == "__main__":
    main()
