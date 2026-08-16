import json
import threading
from typing import Callable, Optional
from core.mutator import LayoutOptimizerSA
from core.models import Layout
from pathlib import Path
import yaml


config = {}
with open(Path(__file__).resolve().parents[1] / "config" / "moves.yaml") as f:
    moves_config = yaml.safe_load(f)

with open(Path(__file__).resolve().parents[1] / "config" / "statistic.json") as f:
    statistic = json.load(f)

class OptimizationProcessor:
    """Driver for the optimization life cycle in the individual thread."""
    def __init__(self, statistic: dict, moves_config: dict):
        self.statistic = statistic
        self.moves_config = moves_config
        self.stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.is_running = False
        self.optimizer = None

    def start(
        self,
        initial_layout: Layout,
        on_progress: Callable[[Layout, int, float], None],
        on_done: Callable[[Layout], None],
        n_iterations: int = 200000,
    ):
        if self.is_running:
            return  # already running/ignore the state

        self.stop_event.clear()
        self.is_running = True

        def worker():
            if self.optimizer is None:
                self.optimizer = LayoutOptimizerSA(
                    initial_layout=initial_layout,
                    statistics=self.statistic,
                    moves_config=self.moves_config,
                    config=config,
                    stop_event=self.stop_event,
                )
            result = self.optimizer.run_optimization(
                iterations=n_iterations,
                ui_callback=on_progress,
            )
            self.is_running = False
            on_done(result)

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_event.set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
