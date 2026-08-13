
import copy
import math
import random
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import core.scorer as scoring
from core.models import Layout


class LayoutOptimizerSA:
    """Simulated-annealing optimizer for a validated keyboard ``Layout``."""

    def __init__(
        self,
        initial_layout: Layout,
        text_data: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        if not isinstance(initial_layout, Layout):
            raise TypeError("initial_layout must be a Layout")
        if not isinstance(text_data, str) or not text_data:
            raise ValueError("text_data must be a non-empty string")

        config = config or {}
        self.moves_config = config.get("moves_config") or scoring.load_moves_config(
            config.get(
                "moves_path",
                Path(__file__).resolve().parents[1] / "config" / "moves.yaml",
            )
        )
        self.best_layout = copy.deepcopy(initial_layout)
        self.text_data = text_data
        self.best_score = self._score(self.best_layout)
        self.best_id = str(uuid.uuid4())[:8]

        self.start_temp = config.get("start_temp", 2.0)
        self.end_temp = config.get("end_temp", 0.01)
        self.stall_window = config.get("stall_window", 300)
        self.reheat_factor = config.get("reheat_factor", 1.6)
        self.tabu_size = config.get("tabu_size", 50)
        if self.start_temp <= 0 or self.end_temp <= 0:
            raise ValueError("start_temp and end_temp must be positive")
        if self.stall_window <= 0 or self.tabu_size < 0:
            raise ValueError("stall_window must be positive and tabu_size cannot be negative")
        self.rng = random.Random(config.get("seed", 42))

        # поточний "робочий" стан SA (окремо від best — SA інколи стоїть
        # на гіршому за best стані, це механізм проти цугцвангу)
        self.current_layout = copy.deepcopy(initial_layout)
        self.current_score = self.best_score

        self.history = [{"iter": 0, "id": self.best_id, "score": self.best_score, "event": "seed"}]
        self.tabu = [self._signature(self.current_layout)]

    def _score(self, layout: Layout) -> float:
        return scoring.calculate_total_penalty(
            layout, self.text_data, self.moves_config
        )

    # -----------------------------------------------------------
    # Мутаційні оператори — усі працюють у ТВОЄМУ форматі (list[Key])
    # -----------------------------------------------------------

    def _unfrozen(self, layout: Layout):
        """Return only characters the optimizer is allowed to relocate."""
        return [
            key
            for key in layout.keys
            if not key.is_frozen and key.char and len(key.char) == 1
        ]

    @staticmethod
    def _require_mutable_keys(keys, required):
        if len(keys) < required:
            raise ValueError(
                f"mutation requires {required} mutable keys; found {len(keys)}"
            )

    def _mutate_single_swap(self, layout: Layout) -> Layout:
        candidate = copy.deepcopy(layout)
        unfrozen = self._unfrozen(candidate)
        self._require_mutable_keys(unfrozen, 2)
        k1, k2 = self.rng.sample(unfrozen, 2)
        k1.char, k2.char = k2.char, k1.char
        return candidate

    def _mutate_segment_shift(self, layout: Layout) -> Layout:
        """3-циклічний зсув: недосяжний одним swap."""
        candidate = copy.deepcopy(layout)
        unfrozen = self._unfrozen(candidate)
        self._require_mutable_keys(unfrozen, 3)
        k1, k2, k3 = self.rng.sample(unfrozen, 3)
        k1.char, k2.char, k3.char = k3.char, k1.char, k2.char
        return candidate

    def _mutate_double_swap(self, layout: Layout) -> Layout:
        """Два незалежні swap за один хід (4 позиції рухаються разом)."""
        candidate = copy.deepcopy(layout)
        unfrozen = self._unfrozen(candidate)
        self._require_mutable_keys(unfrozen, 4)
        k1, k2, k3, k4 = self.rng.sample(unfrozen, 4)
        k1.char, k2.char = k2.char, k1.char
        k3.char, k4.char = k4.char, k3.char
        return candidate

    MUTATION_LADDER_NAMES = ["single_swap", "segment_shift", "double_swap"]

    def _apply_mutation(self, layout: Layout, ladder_index: int) -> Layout:
        fn = [self._mutate_single_swap, self._mutate_segment_shift, self._mutate_double_swap]
        mutable_count = len(self._unfrozen(layout))
        max_ladder_index = 2 if mutable_count >= 4 else 1 if mutable_count >= 3 else 0
        fn = fn[min(ladder_index, max_ladder_index)]
        return fn(layout)

    def _signature(self, layout: Layout):
        """Компактний підпис стану для tabu-списку (порядок char по позиціях)."""
        return tuple(k.char for k in layout.keys)

    # -----------------------------------------------------------
    # Основний цикл
    # -----------------------------------------------------------

    def run_optimization(
        self,
        iterations: int = 10000,
        ui_callback: Optional[Callable[..., None]] = None,
    ) -> Layout:
        if iterations < 1:
            raise ValueError("iterations must be at least 1")
        self._require_mutable_keys(self._unfrozen(self.current_layout), 2)
        stall_counter = 0
        ladder_index = 0
        temp = self.start_temp
        cooling = (self.end_temp / self.start_temp) ** (1.0 / max(iterations, 1))

        for i in range(1, iterations + 1):
            candidate = self._apply_mutation(self.current_layout, ladder_index)
            sig = self._signature(candidate)

            if sig in self.tabu:
                # цей стан вже недавно відвідували — пропускаємо ітерацію,
                # без витрати на переоцінку
                continue

            candidate_score = self._score(candidate)
            delta = candidate_score - self.current_score

            accepted = False
            if delta < 0:
                accepted = True
            else:
                p = math.exp(-delta / max(temp, 1e-9))
                if self.rng.random() < p:
                    accepted = True

            if accepted:
                self.current_layout = candidate
                self.current_score = candidate_score
                self.tabu.append(sig)
                if len(self.tabu) > self.tabu_size:
                    self.tabu.pop(0)

            if candidate_score < self.best_score:
                self.best_layout = copy.deepcopy(candidate)
                self.best_score = candidate_score
                self.best_id = str(uuid.uuid4())[:8]
                self.history.append({
                    "iter": i, "id": self.best_id, "score": self.best_score,
                    "event": f"improve via {self.MUTATION_LADDER_NAMES[ladder_index]}"
                })
                stall_counter = 0
                ladder_index = 0
            else:
                stall_counter += 1

            if stall_counter > 0 and stall_counter % self.stall_window == 0:
                mutable_count = len(self._unfrozen(self.current_layout))
                max_ladder_index = 2 if mutable_count >= 4 else 1 if mutable_count >= 3 else 0
                if ladder_index < max_ladder_index:
                    ladder_index += 1
                    self.history.append({
                        "iter": i, "id": None, "score": self.current_score,
                        "event": f"escalate -> {self.MUTATION_LADDER_NAMES[ladder_index]}"
                    })
                else:
                    temp *= self.reheat_factor
                    self.history.append({
                        "iter": i, "id": None, "score": self.current_score,
                        "event": f"reheat -> temp={temp:.4f}"
                    })

            temp *= cooling

            if ui_callback and i % 500 == 0:
                ui_callback(self.best_layout, self.best_score, current_iteration=i)

        self.best_layout.score = scoring.MovementScoringEngine(
            self.best_layout.keys, self.moves_config
        ).score_movements(self.text_data)
        return copy.deepcopy(self.best_layout)
