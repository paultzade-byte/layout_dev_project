"""Оптимізація без GUI: один прогін SA для геометрії, друк розкладки і штрафу.

    python main.py [--geometry corne_42|generic_105_alpha] [--iterations N]
                   [--seed S] [--out LAYOUT.json]

Важкі прогони — під квотою CPU через cgroup (див. CLAUDE.md):
    systemd-run --user --scope -q -p CPUQuota=60% nice -n 10 \
      env OPENBLAS_NUM_THREADS=1 .venv/bin/python main.py ...
--out пише у форматі Rec>>.
GUI: python -m uiux.app
"""

import argparse
import json
import time

from config.main_config import DEFAULT_GEOMETRY, GEOMETRIES, MUTATOR_CONFIG, STATISTIC, geometry_config, load_moves
from core.layout_factory import build_layout
from core.mutator import LayoutOptimizerSA
from core.scorer import MovementScoringEngine

SCORE_SCALE = 1e8  # та сама шкала, що в GUI і scripts/


def grid(layout) -> str:
    rows = {}
    for key in layout.keys:
        rows.setdefault(key.row, {}).setdefault(key.hand.value, []).append(key)
    lines = []
    for row in sorted(rows):
        halves = [" ".join(k.char or "·" for k in sorted(rows[row].get(hand, []), key=lambda k: k.col))
                  for hand in ("left", "right")]
        lines.append(f"  {halves[0]:>24}    {halves[1]}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--geometry", choices=sorted(GEOMETRIES), default=DEFAULT_GEOMETRY)
    parser.add_argument("--iterations", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", help="куди записати розкладку (формат Rec>>)")
    args = parser.parse_args(argv)

    moves = load_moves(args.geometry)
    layout = build_layout(geometry_config(args.geometry))
    config = dict(MUTATOR_CONFIG, seed=args.seed if args.seed is not None else int(time.time() * 1000) % 2**32)

    engine = MovementScoringEngine(layout.keys, moves).prepare_statistics(STATISTIC)
    start = engine.score().total_penalty / SCORE_SCALE

    optimizer = LayoutOptimizerSA(layout, STATISTIC, moves, config=config)
    best = optimizer.run_optimization(layout, iterations=args.iterations)
    score = engine.update_layout(best.keys).score().total_penalty / SCORE_SCALE

    print(f"{args.geometry}: штраф {start:.2f} -> {score:.2f} ({args.iterations} ітерацій, seed {config['seed']})")
    print(grid(best))
    if args.out:
        data = [{"position_id": k.position_id, "char": k.char, "is_frozen": k.is_frozen} for k in best.keys]
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"записано: {args.out}")
    return best, score


if __name__ == "__main__":
    main()
