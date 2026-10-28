"""Шар CYR на клавіатурі <-> розкладка оптимізатора (формат Rec>>).

Холди прив'язані до позицій, тапи — до літер: на кожній позиції лишається
поточний behavior (шифт на середньому пальці, Ctrl+C/V, &lt на ї і комі…),
замінюється лише кейкод тапу. Літера -> кейкод ЙЦУКЕН за xkb `ua`
(`studio.UA_KEYCODES`).

    # розкладка -> новий дамп (на основі поточного), далі studio.py write
    python scripts/zmk/cyr_from_layout.py build LAYOUT.json BASE_DUMP.json OUT_DUMP.json
    # шар з дампу -> розкладка оптимізатора (перевірка / Rec<<)
    python scripts/zmk/cyr_from_layout.py extract DUMP.json OUT_LAYOUT.json
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio import TAP_PARAM, UA_CHARS, UA_KEYCODES, _norm, find_layer  # noqa: E402
from config.main_config import GEOMETRY_CONFIG  # noqa: E402

LAYER = "CYR"
# Перша позиція кожного ряду Eyelash Corne для лівої і правої руки.
_LEFT_BASE = {0: 0, 1: 13, 2: 28}
_RIGHT_BASE = {0: 7, 1: 22, 2: 36}


def eyelash_position(key):
    """Позиція geometry.json (corne_42) -> позиція Eyelash Corne.

    Ліва рука: col 0 (зовнішня мізинця) … 5 (дотична вказівного).
    Права: col 1 (дотична вказівного) … 6 (зовнішня мізинця). Тхамби — None.
    """
    if key["row"] not in _LEFT_BASE:
        return None
    if key["hand"] == "L":
        return _LEFT_BASE[key["row"]] + key["col"]
    return _RIGHT_BASE[key["row"]] + key["col"] - 1


def position_map():
    return {k["id"]: eyelash_position(k) for k in GEOMETRY_CONFIG["positions"]}


def tap_param(dump, binding, pos):
    name = dump["behaviors"][binding[0]]
    if name not in TAP_PARAM:
        raise SystemExit(f"позиція {pos}: behavior {name!r} без тапу-кейкоду")
    return TAP_PARAM[name]


def build(layout, base):
    dump = copy.deepcopy(base)
    bindings = find_layer(dump, LAYER)["bindings"]
    pmap = position_map()
    placed = set()
    for item in layout:
        char, pos = item["char"], pmap.get(item["position_id"])
        if pos is None or char not in UA_KEYCODES:
            continue  # тхамби, порожні кути, SPA/CE
        idx = tap_param(dump, bindings[pos], pos)
        bindings[pos][idx] = UA_KEYCODES[char]
        placed.add(pos)
    # інші позиції шару не повинні дублювати літеру з нової розкладки
    new_chars = {UA_CHARS[bindings[p][tap_param(dump, bindings[p], p)]] for p in placed}
    for pos, b in enumerate(bindings):
        name = dump["behaviors"][b[0]]
        if pos not in placed and name in TAP_PARAM and UA_CHARS.get(b[TAP_PARAM[name]]) in new_chars:
            raise SystemExit(f"позиція {pos} поза розкладкою дублює «{UA_CHARS[b[TAP_PARAM[name]]]}»")
    return dump


def extract(dump):
    bindings = find_layer(dump, LAYER)["bindings"]
    layout = []
    for opt_id, pos in sorted(position_map().items()):
        char = ""
        if pos is not None:
            name = dump["behaviors"][bindings[pos][0]]
            if name in TAP_PARAM:
                char = UA_CHARS.get(bindings[pos][TAP_PARAM[name]], "")
        layout.append({"position_id": opt_id, "char": char, "is_frozen": False})
    return layout


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("layout")
    p.add_argument("base")
    p.add_argument("out")
    p = sub.add_parser("extract")
    p.add_argument("dump")
    p.add_argument("out")
    args = parser.parse_args()

    if args.cmd == "build":
        layout = json.loads(Path(args.layout).read_text(encoding="utf-8"))
        base = _norm(json.loads(Path(args.base).read_text(encoding="utf-8")))
        result = build(layout, base)
    else:
        result = extract(_norm(json.loads(Path(args.dump).read_text(encoding="utf-8"))))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"записано {args.out}")


if __name__ == "__main__":
    main()
