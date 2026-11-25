"""Де поставити апостроф на звичайній клавіатурі (рішення 10, docs/PLAN_standard.md).

Слотів для символів 35 на 35 символів (33 літери + . + ,), тож апостроф —
на AltGr-шарі над якоюсь клавішею. Для кожної клавіші-хоста рахуємо повний
штраф розкладки з апострофом там: віртуальна позиція з тими самими рядом,
колонкою, x і пальцем, що й хост, а натискання дорожче на акорд AltGr
(великий палець): base_effort хоста + --altgr-cost (типово 1.0 — як одне
натискання великим пальцем). Літери розкладки не рухаються.

Варіант «а» для порівняння: апостроф на ` (власна клавіша), а символ, що
там стояв (кома), — на AltGr найкращого хоста.

    python scripts/apostrophe_altgr.py LAYOUT.json [--altgr-cost 1.0] [--top 8]
Під квотою CPU (systemd-run): ~35 хостів x prepare_statistics.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.main_config import STATISTIC, geometry_config, load_moves  # noqa: E402
from core.layout_factory import build_layout  # noqa: E402
from core.scorer import MovementScoringEngine  # noqa: E402

GEOMETRY = "generic_105_alpha"
VIRTUAL_ID = 1000
SCALE = 1e8


def chars_of(path):
    return {d["position_id"]: d["char"] for d in json.loads(Path(path).read_text(encoding="utf-8"))}


def score_with(chars, extra_char, host, altgr_cost, moves):
    """Штраф розкладки chars + extra_char на AltGr над позицією host."""
    geometry = copy.deepcopy(geometry_config(GEOMETRY))
    host_pos = next(p for p in geometry["positions"] if p["id"] == host)
    layout = build_layout(geometry)
    for key in layout.keys:
        key.char = chars.get(key.position_id, key.char)
    engine = MovementScoringEngine(layout.keys, moves)
    host_effort = engine._pos_effort[engine._pos_index[host]]
    virtual = dict(host_pos, id=VIRTUAL_ID, default=extra_char,
                   base_cost=1.0 + altgr_cost / host_effort)  # effort хоста + altgr_cost
    virtual.pop("role", None)
    geometry["positions"].append(virtual)
    layout = build_layout(geometry)
    for key in layout.keys:
        if key.position_id != VIRTUAL_ID:
            key.char = chars.get(key.position_id, key.char)
    engine = MovementScoringEngine(layout.keys, moves).prepare_statistics(STATISTIC)
    return engine.score().total_penalty / SCALE


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("layout")
    parser.add_argument("--altgr-cost", type=float, default=1.0)
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args()

    moves = load_moves(GEOMETRY)
    chars = chars_of(args.layout)
    geometry = geometry_config(GEOMETRY)
    hosts = [p["id"] for p in geometry["positions"] if p.get("role") != "mod"]

    results = sorted((score_with(chars, "'", h, args.altgr_cost, moves), h) for h in hosts)
    print(f"б) апостроф на AltGr (акорд +{args.altgr_cost}), найкращі хости:")
    for score, host in results[:args.top]:
        print(f"  {score:8.2f}  над «{chars.get(host, '?')}» (позиція {host})")

    backtick = 38
    displaced = chars.get(backtick)
    swapped = {**chars, backtick: "'"}
    alt = sorted((score_with(swapped, displaced, h, args.altgr_cost, moves), h) for h in hosts if h != backtick)
    score, host = alt[0]
    print(f"\nа) апостроф на ` , «{displaced}» на AltGr над «{chars.get(host, '?')}»: {score:.2f}")
    best_b = results[0][0]
    print(f"\nкраще: {'б (AltGr)' if best_b <= score else 'а (`)'} на {abs(best_b - score):.2f}")


if __name__ == "__main__":
    main()
