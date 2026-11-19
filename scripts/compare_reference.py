"""Порівняння результату оптимізатора з еталонною розкладкою автора.

Еталон (config/reference_layout.json) — розкладка, до якої автор уже майже
звик. Після кожної зміни ваг у moves.yaml варто перевірити, що оптимізатор
не тікає від неї в структуру, яка вважається неробочою (напр. усі голосні
на одній руці): дивимось частку чергування рук, розподіл голосних і внесок
кожного компонента штрафу.

Запуск з кореня проєкту (під обмеженням CPU):
    cpulimit -l 60 -f -m -q -- python scripts/compare_reference.py [ітерацій]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC
from core.layout_factory import build_layout
from core.mutator import LayoutOptimizerSA
from core.scorer import MovementScoringEngine

PROJ_DIR = Path(__file__).resolve().parents[1]
REFERENCE_PATH = PROJ_DIR / "config" / "reference_layout.json"
MUTATOR_CONFIG_PATH = PROJ_DIR / "config" / "mutator_config.json"
VOWELS = set("аеєиіїоуюя")


def load_layout(path):
    layout = build_layout(GEOMETRY_CONFIG)
    chars = {d["position_id"]: d["char"] for d in json.loads(Path(path).read_text(encoding="utf-8"))}
    for key in layout.keys:
        if key.position_id in chars:
            key.char = chars[key.position_id]
    return layout


def grid(layout):
    lines = []
    for row, name in enumerate(("верх", "дім ", "низ ")):
        left = sorted((k for k in layout.keys if k.row == row and k.hand.value == "left"), key=lambda k: k.col)
        right = sorted((k for k in layout.keys if k.row == row and k.hand.value == "right"), key=lambda k: k.col)
        lines.append(f"  {name} {' '.join(k.char for k in left):>13}    {' '.join(k.char for k in right)}")
    return "\n".join(lines)


def summary(layout):
    hand = {k.char: k.hand.value for k in layout.keys if k.char}
    total = alternating = 0
    for pair, freq in STATISTIC["bigrams"].items():
        if pair[0] in hand and pair[1] in hand:
            total += freq
            alternating += freq * (hand[pair[0]] != hand[pair[1]])
    uni = STATISTIC["unigrams"]
    vowel_left = sum(uni.get(c, 0) for c in VOWELS if hand.get(c) == "left")
    vowel_all = sum(uni.get(c, 0) for c in VOWELS if c in hand)
    return (f"  чергування рук у біграмах: {100 * alternating / total:.0f}%   "
            f"голосні ліва/права: {100 * vowel_left / vowel_all:.0f}/{100 - 100 * vowel_left / vowel_all:.0f}%")


def main():
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    reference = load_layout(REFERENCE_PATH)
    config = json.loads(MUTATOR_CONFIG_PATH.read_text())
    optimizer = LayoutOptimizerSA(build_layout(GEOMETRY_CONFIG), STATISTIC, MOVES_CONFIG, config=config)
    optimized = optimizer.run_optimization(build_layout(GEOMETRY_CONFIG), iterations=iterations)

    print("ЕТАЛОН\n" + grid(reference) + "\n" + summary(reference))
    print(f"ОПТИМІЗАТОР ({iterations} ітерацій)\n" + grid(optimized) + "\n" + summary(optimized))

    engine = MovementScoringEngine(reference.keys, MOVES_CONFIG).prepare_statistics(STATISTIC)
    ref_metrics = vars(engine.score())
    engine.update_layout(optimized.keys)
    opt_metrics = vars(engine.score())
    print(f"\n{'компонент (x1e8)':32}{'еталон':>10}{'оптим.':>10}{'різниця':>10}")
    for name, ref_value in ref_metrics.items():
        opt_value = opt_metrics[name]
        if ref_value or opt_value:
            print(f"{name:32}{ref_value / 1e8:10.1f}{opt_value / 1e8:10.1f}{(opt_value - ref_value) / 1e8:+10.1f}")


if __name__ == "__main__":
    main()
