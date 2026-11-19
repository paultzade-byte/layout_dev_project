"""Порівняння двох розкладок: компоненти штрафу і n-грами/літери, що дають різницю.

    cpulimit -l 60 -f -m -q -- python scripts/compare_layouts.py A.json B.json [топ]

Плюс у різниці — B гірша за A. hand_runs (по словах) — лише компонентом.
"""
import json
import sys

import numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC
from core.layout_factory import build_layout
from core.scorer import MovementScoringEngine
from compare_reference import grid, summary

def load(p):
    lay = build_layout(GEOMETRY_CONFIG)
    ch = {d['position_id']: d['char'] for d in json.load(open(p))}
    for k in lay.keys: k.char = ch.get(k.position_id, k.char)
    return lay
A = load(sys.argv[1]); B = load(sys.argv[2]); TOP = int(sys.argv[3]) if len(sys.argv) > 3 else 30
eng = MovementScoringEngine(A.keys, MOVES_CONFIG).prepare_statistics(STATISTIC)
def items(e):
    out = {}
    for name, fam in e._families.items():
        if fam.by_hand: continue
        code = fam.code(fam.keys)
        for field, table in fam.tables.items():
            out[(name, field)] = table[code] * fam.weight
    pos = e.position[e._unigram_idx]
    out[('unigrams', 'base_effort')] = e._pos_effort[pos] * e._unigram_weight
    return out
ma = vars(eng.score()); ia = items(eng)
eng.update_layout(B.keys); mb = vars(eng.score()); ib = items(eng)
print('A\n' + grid(A) + '\n' + summary(A)); print('B\n' + grid(B) + '\n' + summary(B))
print(f"\n{'компонент':32}{'A':>9}{'B':>9}{'різн.':>9}")
for k in ma:
    if ma[k] or mb[k]: print(f"{k:32}{ma[k]/1e8:9.2f}{mb[k]/1e8:9.2f}{(mb[k]-ma[k])/1e8:+9.2f}")
chars = eng.chars
def label(name, j):
    fam = eng._families.get(name)
    if name == 'unigrams': return chars[eng._unigram_idx[j]]
    return ''.join(chars[i] for i in fam.keys[:, j])
# per n-gram total diff across fields
agg = {}
for (name, field), va in ia.items():
    d = ib[(name, field)] - va
    for j in np.nonzero(d)[0]:
        key = (name, label(name, j)); agg.setdefault(key, {}); agg[key][field] = agg[key].get(field, 0) + d[j]
rows = sorted(((sum(v.values()), k, v) for k, v in agg.items()), key=lambda t: t[0])
fmt = lambda t: f"{t[1][0][:4]:5}{t[1][1]:5}{t[0]/1e8:+7.2f}  " + ', '.join(f"{f.replace('_penalty','')} {x/1e8:+.2f}" for f, x in sorted(t[2].items(), key=lambda z: -abs(z[1])) if abs(x) > 1e6)
print('\nДЕ B ГІРША:'); [print(fmt(t)) for t in rows[::-1][:TOP]]
print('\nДЕ B КРАЩА:'); [print(fmt(t)) for t in rows[:TOP // 2]]
