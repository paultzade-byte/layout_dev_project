"""Звіт по розкладках однієї геометрії: штраф, «vs перша», компоненти, метрики.

    python scripts/layout_report.py [--geometry NAME] LAYOUT.json [LAYOUT2.json ...]

'-' замість файлу — типова розкладка геометрії (для generic_105_alpha це
ЙЦУКЕН, тож `- best.json` = «наскільки краще за ЙЦУКЕН»). Перша колонка —
база для відсотків. Під cpulimit (CLAUDE.md).
"""

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.main_config import ACTIVE, GEOMETRIES, STATISTIC, geometry_config, load_moves  # noqa: E402
from core.layout_factory import build_layout  # noqa: E402
from core.metrics import METRIC_TITLES, layout_metrics  # noqa: E402
from core.models import ScoreMetrics  # noqa: E402
from core.scorer import MovementScoringEngine  # noqa: E402

SCALE = 1e8


def load(path, geometry):
    layout = build_layout(geometry)
    if path != "-":
        chars = {d["position_id"]: d["char"] for d in json.loads(Path(path).read_text(encoding="utf-8"))}
        for key in layout.keys:
            if key.position_id in chars:
                key.char = chars[key.position_id]
    return layout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("layouts", nargs="+")
    parser.add_argument("--geometry", choices=sorted(GEOMETRIES), default=ACTIVE)
    args = parser.parse_args(argv)

    geometry = geometry_config(args.geometry)
    layouts = [load(p, geometry) for p in args.layouts]
    engine = MovementScoringEngine(layouts[0].keys, load_moves(args.geometry)).prepare_statistics(STATISTIC)
    scores = [engine.update_layout(l.keys).score() for l in layouts]
    metrics = [layout_metrics(l.keys, STATISTIC) for l in layouts]

    names = ["ЙЦУКЕН" if p == "-" and args.geometry == "generic_105_alpha" else Path(p).stem[:14]
             for p in args.layouts]
    width = max(14, *(len(n) for n in names))
    row = lambda title, cells: print(f"{title:<26}" + "".join(f"{c:>{width + 2}}" for c in cells))

    print(f"геометрія {args.geometry}")
    row("", names)
    base = scores[0].total_penalty
    row("штраф", [f"{s.total_penalty / SCALE:.2f}" for s in scores])
    row("vs перша", [f"{100 * (s.total_penalty / base - 1):+.1f}%" for s in scores])
    print("компоненти:")
    for f in fields(ScoreMetrics):
        if f.name == "total_penalty":
            continue
        values = [getattr(s, f.name) / SCALE for s in scores]
        if any(abs(v) >= 0.05 for v in values):
            row("  " + f.name.replace("_penalty", ""), [f"{v:.2f}" for v in values])
    print("метрики, %:")
    for key, title in METRIC_TITLES.items():
        row("  " + title, [f"{m[key]:.1f}" for m in metrics])


if __name__ == "__main__":
    main()
