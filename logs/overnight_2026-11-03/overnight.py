"""Resumable: stages with existing *_best.json / *_scores.txt are skipped.
Run: OPENBLAS_NUM_THREADS=1 cpulimit -l 60 -f -m -q -- .venv/bin/python logs/overnight_2026-11-03/overnight.py >> logs/overnight_2026-11-03/driver.log 2>&1
Overnight: polish from f + foreign_finger (index<->pinky) weight experiment. Weights patched in memory only."""
import json, os, sys, time, contextlib
os.nice(10)
ROOT = os.path.expanduser('~/Documents/Portfolio/layout_dev_project'); os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT + '/scripts')
OUT = ROOT + '/logs/overnight_2026-11-03'
import multistart
from compare_reference import MOVES_CONFIG, GEOMETRY_CONFIG, STATISTIC
from core.layout_factory import build_layout
from core.scorer import MovementScoringEngine
F = 'config/layout_paul_2026-11-03f.json'
NAMED = {'seed5': 'config/layout_seed5.json', 'e': 'config/layout_paul_2026-11-03e.json', 'f': F}

def load(p):
    lay = build_layout(GEOMETRY_CONFIG); ch = {d['position_id']: d['char'] for d in json.load(open(p))}
    for k in lay.keys: k.char = ch.get(k.position_id, k.char)
    return lay

def run(tag, argv):
    if os.path.exists(f'{OUT}/{tag}_best.json'):
        print('skip (done)', tag, flush=True); return
    with open(f'{OUT}/{tag}.txt', 'w') as fh, contextlib.redirect_stdout(fh):
        sys.argv = ['multistart.py'] + argv + ['--out', f'{OUT}/{tag}_best.json']
        t = time.time(); multistart.main(); print(f'\n{time.time()-t:.0f}s')

def scores(tag):
    if os.path.exists(f'{OUT}/{tag}_scores.txt'): return
    eng = MovementScoringEngine(load(F).keys, MOVES_CONFIG).prepare_statistics(STATISTIC)
    with open(f'{OUT}/{tag}_scores.txt', 'w') as fh:
        for n, p in NAMED.items():
            eng.update_layout(load(p).keys); fh.write(f'{n} {eng.score().total_penalty/1e8:.2f}\n')

fa = MOVES_CONFIG['finger_alternation']
print('start', time.ctime(), flush=True)
run('A_cur_polish_f', ['30000', '4', '--from', F]); print('A done', time.ctime(), flush=True)
for val, tag in [(0.3, 'B_ff03'), (0.0, 'C_ff00')]:
    fa['foreign_finger'] = val
    scores(tag)
    run(tag + '_scratch', ['100000', '8'])
    run(tag + '_polish_f', ['30000', '4', '--from', F])
    print(tag, 'done', time.ctime(), flush=True)
print('ALL DONE', time.ctime(), flush=True)
