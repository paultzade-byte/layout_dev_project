"""Multi-start: N незалежних прогонів SA з різними seed, найкращий —
результат, розкид між ними — міра довіри.

Якщо кілька стартів сходяться до тієї ж розкладки, що й найкращий, — це,
ймовірно, глобальний мінімум моделі. Якщо всі різні — SA бракує ітерацій.

Запуск з кореня проєкту (під обмеженням CPU; прогони послідовні — під
cpulimit паралельність не дає швидкості):
    cpulimit -l 60 -f -m -q -- python scripts/multistart.py ІТЕРАЦІЙ СТАРТІВ [--from JSON] [--out JSON]
  --from  стартова розкладка у форматі Rec>> (config/recorded_layout.json):
          літери і заморожені (is_frozen) клавіші — їх SA не рухає
  --out   куди записати найкращу розкладку (той самий формат; щоб відкрити
          в GUI через Rec<<, запиши в config/recorded_layout.json)
напр.:
    cpulimit -l 60 -f -m -q -- python scripts/multistart.py 100000 8 --out /tmp/best.json
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_reference import GEOMETRY_CONFIG, MOVES_CONFIG, MUTATOR_CONFIG_PATH, STATISTIC, grid, summary
from core.layout_factory import build_layout
from core.mutator import LayoutOptimizerSA

SCALE = 1e8  # як у compare_reference / sa_bench


def load_start(path):
    layout = build_layout(GEOMETRY_CONFIG)
    if path:
        state = {d["position_id"]: d for d in json.loads(Path(path).read_text(encoding="utf-8"))}
        for key in layout.keys:
            if key.position_id in state:
                key.char = state[key.position_id]["char"]
                key.is_frozen = state[key.position_id]["is_frozen"]
    return layout


def signature(layout):
    return tuple(key.char for key in layout.keys)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("iterations", type=int)
    parser.add_argument("starts", type=int)
    parser.add_argument("--from", dest="start_path")
    parser.add_argument("--out")
    parser.add_argument("--first-seed", type=int, default=1)
    args = parser.parse_args()

    base_config = json.loads(MUTATOR_CONFIG_PATH.read_text())
    runs = []
    for seed in range(args.first_seed, args.first_seed + args.starts):
        started = time.time()
        config = {**base_config, "seed": seed}
        optimizer = LayoutOptimizerSA(load_start(args.start_path), STATISTIC, MOVES_CONFIG, config=config)
        best = optimizer.run_optimization(load_start(args.start_path), iterations=args.iterations)
        improves = [h["iter"] for h in optimizer.history if h["event"].startswith("improve")]
        runs.append({"seed": seed, "score": optimizer.best_score / SCALE, "layout": best,
                     "last_improve": improves[-1] if improves else 0})
        print(f"seed {seed}: {runs[-1]['score']:.2f}  last improve @{runs[-1]['last_improve']}  "
              f"{time.time() - started:.0f}s", flush=True)

    runs.sort(key=lambda r: r["score"])
    best = runs[0]
    scores = [r["score"] for r in runs]
    same = sum(signature(r["layout"]) == signature(best["layout"]) for r in runs)
    print(f"\n{args.starts} стартів x {args.iterations} ітерацій: best {scores[0]:.2f}  "
          f"median {statistics.median(scores):.2f}  worst {scores[-1]:.2f}")
    print(f"до тієї ж розкладки, що й best, дійшли {same} з {args.starts}")
    print(f"\nНАЙКРАЩА (seed {best['seed']})\n" + grid(best["layout"]) + "\n" + summary(best["layout"]))
    for run in runs[1:3]:
        if signature(run["layout"]) != signature(best["layout"]):
            print(f"\nseed {run['seed']} ({run['score']:.2f})\n" + grid(run["layout"]))

    if args.out:
        data = [{"position_id": k.position_id, "char": k.char, "is_frozen": k.is_frozen}
                for k in best["layout"].keys]
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nзаписано: {args.out}")


if __name__ == "__main__":
    main()
