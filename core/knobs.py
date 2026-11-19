"""Повзунки впливу (фаза 4 docs/PLAN_standard.md): кілька зрозумілих ручок
замість десятків ваг.

Кожен повзунок множить групу ваг з moves-файлу. Положення — плавне число
-2..+2, а діє його крок (округлення до найближчого цілого: 5 діапазонів):

    крок   -2     -1     0      +1     +2
    ×      0.5    0.71   1      1.41   2      (2 ** (крок / 2))

Ціль з power p множиться на ×**p (p = -1 — у протилежний бік, 0.5 — м'якше).
Крок 0 — ваги рівно як у файлі (нічого не множиться), тож з усіма
повзунками посередині модель та сама до біта.

«Близькість до ЙЦУКЕН» — окремий штраф (core/scorer.py, секція `closeness`),
вмикається прапорцем; повзунок крутить його вагу в тих самих ×0.5…×2.
"""

import copy
from dataclasses import dataclass
from typing import Dict, Tuple

STEP_TITLES = {-2: "дуже мало", -1: "менше", 0: "рекомендовано", 1: "більше", 2: "максимум"}
LIMIT = 2


@dataclass(frozen=True)
class Knob:
    id: str
    title: str
    left: str                     # підпис лівого краю
    right: str                    # підпис правого краю
    targets: Tuple[Tuple[Tuple[str, ...], float], ...]   # (шлях у moves, power)
    geometry: str | None = None   # лише для цієї геометрії (None — для всіх)


KNOBS = (
    Knob("home_row", "Домашній ряд", "байдуже", "якомога більше", (
        (("base_effort", "row_multiplier", "home_row"), -0.5),
        (("base_effort", "row_multiplier", "top"), 0.5),
        (("base_effort", "row_multiplier", "bottom"), 0.5),
        (("base_effort", "row_multiplier", "bottom_left"), 0.5),
    )),
    Knob("vertical", "Вертикальні переходи одним пальцем", "дозволити", "уникати", (
        (("same_finger", "vertical"), 1.0),
        (("same_finger", "diagonal_down"), 1.0),
        (("same_finger", "diagonal_up"), 1.0),
        (("same_finger", "skip_row", "max"), 1.0),
    )),
    Knob("pinky", "Берегти мізинці", "менше", "більше", (
        (("base_effort", "finger_multiplier", "pinky"), 0.5),
        (("base_effort", "column_multiplier", "col_pinky"), 0.5),
        (("finger_load", "cap", "pinky"), -1.0),
    )),
    Knob("alternation", "Перекати ↔ чергування рук", "більше перекатів", "більше чергування", (
        (("hand_runs", "overload"), 1.0),
        (("hand_runs", "overload_step"), 1.0),
        (("hand_runs", "single"), -1.0),
        (("finger_alternation", "brother_finger"), -1.0),   # бонус (від'ємний): праворуч — менший
        (("roll_rows", "natural_arc"), -1.0),
    )),
    Knob("closeness", "Близькість до ЙЦУКЕН", "трохи", "дуже", (
        (("closeness", "weight"), 1.0),
    ), geometry="generic_105_alpha"),
)
KNOBS_BY_ID = {k.id: k for k in KNOBS}


def knobs_for(geometry_name: str):
    return [k for k in KNOBS if k.geometry in (None, geometry_name)]


def step(value: float) -> int:
    """Положення повзунка -> крок -2..+2 (діапазони навколо цілих)."""
    return max(-LIMIT, min(LIMIT, int(round(float(value)))))


def factor(value: float) -> float:
    return 2.0 ** (step(value) / 2)


def reference_positions(geometry: dict) -> Dict[str, int]:
    """{літера: position_id} на ЙЦУКЕН — `default` позицій геометрії."""
    return {p["default"]: p["id"] for p in geometry["positions"]
            if p.get("role") != "mod" and p.get("default")}


def apply(moves: dict, values: Dict[str, float], geometry: dict | None = None,
          closeness: bool = False) -> dict:
    """Нова копія ваг з повзунками values {id: положення}. Відсутні в moves
    шляхи пропускаються (напр. bottom_left у ваг спліта). closeness=True
    вмикає штраф близькості (потрібна geometry — звідти ЙЦУКЕН-позиції)."""
    out = copy.deepcopy(moves)
    for knob_id, value in values.items():
        knob = KNOBS_BY_ID.get(knob_id)
        s = step(value)
        if knob is None or s == 0:
            continue
        f = 2.0 ** (s / 2)
        for path, power in knob.targets:
            node = out
            for part in path[:-1]:
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, dict) and isinstance(node.get(path[-1]), (int, float)):
                node[path[-1]] = node[path[-1]] * f ** power
    if closeness and "closeness" in out and geometry is not None:
        out["closeness"] = dict(out["closeness"], enabled=True, reference=reference_positions(geometry))
    return out


def closeness_metrics(keys, geometry: dict, statistic: dict) -> Dict[str, float]:
    """Скільки літер на своїх ЙЦУКЕН-місцях: штук і % натискань."""
    ref = reference_positions(geometry)
    letters = [k for k in keys if k.char in ref and len(k.char) == 1]
    uni = statistic["unigrams"]
    total = sum(uni.get(k.char, 0.0) for k in letters) or 1.0
    same = [k for k in letters if ref[k.char] == k.position_id]
    return {"in_place": len(same), "of": len(letters),
            "share": 100.0 * sum(uni.get(k.char, 0.0) for k in same) / total}


# ----------------------------------------------------------------------
# Пресети: іменовані положення повзунків (стан як у settings.json → knobs:
# {"values": {id: положення}, "closeness": bool}). Порівнюються за кроками.
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Preset:
    title: str
    values: Tuple[Tuple[str, int], ...] = ()
    closeness: bool = False
    geometry: str | None = None   # лише для цієї геометрії (None — для всіх)

    def state(self) -> dict:
        return {"values": {k: float(v) for k, v in self.values}, "closeness": self.closeness}


RECOMMENDED = Preset("Рекомендовано")
PRESETS = (
    RECOMMENDED,
    Preset("Мінімум змін від ЙЦУКЕН", (("closeness", 2),), closeness=True,
           geometry="generic_105_alpha"),
    Preset("Бережу мізинці", (("pinky", 2), ("home_row", 1))),
    Preset("Більше перекатів", (("alternation", -2), ("vertical", 1))),
)


def presets_for(geometry_name: str):
    return [p for p in PRESETS if p.geometry in (None, geometry_name)]


def state_key(state: dict, geometry_name: str) -> tuple:
    """Що реально діє: кроки повзунків цього режиму + близькість (лише там,
    де вона є). Два стани з однаковим ключем дають однакові ваги."""
    ids = [k.id for k in knobs_for(geometry_name)]
    values = state.get("values") or {}
    closeness = bool(state.get("closeness")) and "closeness" in ids
    steps = tuple(step(values.get(i, 0.0)) for i in ids if i != "closeness" or closeness)
    return steps, closeness


def matching_preset(state: dict, geometry_name: str, custom: Dict[str, dict] | None = None):
    """Назва пресету, що збігається зі станом (вбудовані першими), або None."""
    key = state_key(state, geometry_name)
    for p in presets_for(geometry_name):
        if state_key(p.state(), geometry_name) == key:
            return p.title
    for name, s in (custom or {}).items():
        if state_key(s, geometry_name) == key:
            return name
    return None
