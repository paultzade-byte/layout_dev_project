import yaml
import json
from pathlib import Path

from core.models import *
from core.mutator import LayoutOptimizerSA as mutate
from core.layout_factory import *
from core.scorer import calculate_total_penalty as sc
from config.main_config import GEOMETRY_CONFIG


def load_config(path: str | Path) -> dict:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f)
        elif path.suffix == ".yaml":
            return yaml.safe_load(f)
        else:
            raise ValueError(f"Unsupported file type: {path.suffix}")

def main():
    # configs import
    moves = load_config("config/moves.yaml")
    statistics = load_config("config/statistic.json")

    initial_layout = build_layout(GEOMETRY_CONFIG)
    # or initial_layout = build_layout(some_seed)


    # here we run the mutator
    initial_layout = mutate(initial_layout, statistics, moves).run_optimization()

    # here we run the scorer
    score = sc(initial_layout, statistics, moves)



if __name__ == "__main__":
    main()
