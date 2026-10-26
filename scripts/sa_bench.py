"""Порівняння налаштувань SA на кількох seed.

Розкид між seed (3-4 пункти на 60k ітерацій) більший за різницю між
параметрами SA, тому дивимось середнє по seed, а не один прогін.

Запуск з кореня проєкту (під обмеженням CPU):
    cpulimit -l 60 -f -m -q -- python scripts/sa_bench.py ІТЕРАЦІЙ SEED[,SEED...] ['{json-перевизначення mutator_config}']
напр.:
    cpulimit -l 60 -f -m -q -- python scripts/sa_bench.py 60000 1,2,3 '{"accept_start": 0.2}'
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_reference import GEOMETRY_CONFIG, MOVES_CONFIG, MUTATOR_CONFIG_PATH, STATISTIC, grid, summary
from core.layout_factory import build_layout
from core.mutator import LayoutOptimizerSA


def main():
    iterations = int(sys.argv[1])
    seeds = [int(s) for s in sys.argv[2].split(",")]
    overrides = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    scores = []
    for seed in seeds:
        config = {**json.loads(MUTATOR_CONFIG_PATH.read_text()), **overrides, "seed": seed}
        started = time.time()
        optimizer = LayoutOptimizerSA(build_layout(GEOMETRY_CONFIG), STATISTIC, MOVES_CONFIG, config=config)
        best = optimizer.run_optimization(build_layout(GEOMETRY_CONFIG), iterations=iterations)
        events = [h["event"] for h in optimizer.history]
        improves = [h["iter"] for h in optimizer.history if h["event"].startswith("improve")]
        scores.append(optimizer.best_score / 1e8)
        print(f"seed={seed}: best {scores[-1]:.2f}  last improve @{improves[-1] if improves else 0}  "
              f"accepted {optimizer.accepted_count}  restarts {sum(e.startswith('restart') for e in events)}  "
              f"{time.time() - started:.0f}s")
        print(grid(best) + "\n" + summary(best))
    print(f"{json.dumps(overrides, ensure_ascii=False)}: mean {sum(scores) / len(scores):.2f}  "
          f"min {min(scores):.2f}  max {max(scores):.2f}")


if __name__ == "__main__":
    main()
