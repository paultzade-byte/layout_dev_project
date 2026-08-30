"""Simulated annealing optimizer
with tabu search and ladder cooling(escalation mechanism)."""

import copy
import math
import random
import uuid
import json
import threading

from pathlib import Path
from typing import Any, Callable, Dict, Optional, List

from log.loggers.state_hasher import StateHasher

import core.scorer as scoring
from core.models import Layout, Key, clone_layout

with open(Path(__file__).resolve().parents[1] / "config" / "statistic.json") as f:
    statistics = json.load(f)

with open(Path(__file__).resolve().parents[1] / "config" / "mutator_config.json") as f:
    mutator_config = json.load(f)

class LayoutOptimizerSA:
    """Simulated-annealing optimizer for a validated keyboard ``Layout``."""

    def __init__(
        self,
        initial_layout: Layout,
        statistics: Dict[str, Any],
        moves_config: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.stop_event = stop_event
        self.moves_config = moves_config
        self.best_layout = copy.deepcopy(initial_layout)
        self.statistics = statistics
        self.config = config if config is not None else mutator_config
        print(self.config.get("start_temp"))
        print(type(mutator_config), mutator_config)

        # One long-lived scoring engine for the whole run: the expensive
        # corpus-parsing step (prepare_statistics) happens exactly once here,
        # not on every iteration. _score() below only does the cheap
        # per-mutation update_layout() + vectorized score().
        self.engine = scoring.MovementScoringEngine(self.best_layout.keys, moves_config)
        self.engine.prepare_statistics(statistics)

        self.best_score = self._score(self.best_layout)
        self.best_id = str(uuid.uuid4())[:8]
        self.start_temp = self.config.get("start_temp", 0.01)
        self.end_temp = self.config.get("end_temp", 0.0001)
        self.stall_window = self.config.get("stall_window", 300)
        self.reheat_factor = self.config.get("reheat_factor", 1.6)
        self.tabu_size = self.config.get("tabu_size", 50)
        if self.start_temp <= 0 or self.end_temp <= 0:
            raise ValueError("start_temp and end_temp must be positive")
        if self.stall_window <= 0 or self.tabu_size < 0:
            raise ValueError("stall_window must be positive and tabu_size cannot be negative")
        self.rng = random.Random(self.config.get("seed", 42))

        # поточний "робочий" стан SA (окремо від best — SA інколи стоїть
        # на гіршому за best стані, це механізм проти цугцвангу)
        self.current_layout = copy.deepcopy(initial_layout)
        self.current_score = self.best_score

        self.history = [{"iter": 0, "id": self.best_id, "score": self.best_score, "event": "seed"}]
        self.tabu = [self._signature(self.current_layout)]

        # для основного циклу оптимізації
        self.iterations = self.config.get("iterations", 1)  # кількість ітерацій
        self.stall_counter = self.config.get("stall_counter", 0)  # лічильник застоювань
        self.ladder_index = self.config.get("ladder_index", 0)  # чим він більше, тим масштабніша мутація (0 = swap двох клавіш, 1 = потрійна перестановка, 2 = ще більший блок)
        self.temp = self.config.get("temp", self.start_temp)  # температура(жадібність) чим вона вища, тим більша імовірність прийняття гіршого стану
        self.cooling = self.config.get("cooling", (self.end_temp / self.start_temp) ** (1.1 / max(self.iterations, 1)))  # коефіцієнт охолодження. Чим він більше, тим швидше охолоджується алгоритм
        self.accepted_count = 0  # лічильник прийнятих станів
        self.improved_count = 0  # лічильник покращених станів

    # access to current layout keys
    @property
    def keys(self) -> List[Key]:
        return self.current_layout.keys

    # -----------------------------------------------------------
    # Sync UI-side edits (e.g. freeze toggles made while paused)
    # -----------------------------------------------------------

    def _score(self, layout: Layout) -> float:
        # Cheap path: only refresh per-char geometry (O(num_chars)), then
        # score using the statistics arrays cached once in __init__.
        self.engine.update_layout(layout.keys)
        return self.engine.score().total_penalty

    def sync_full_state(self, reference_layout: Layout) -> None:
        """Тягне і char, і is_frozen з reference_layout (копії UI) у робочі
            копії оптимізатора, за position_id. Потрібно тому що drag/freeze на
            паузі міняють self.layout в App, а не внутрішні current_layout/
            best_layout оптимізатора."""
        state_by_position = {
            key.position_id: (key.char, key.is_frozen)
            for key in reference_layout.keys
        }
        for target in (self.current_layout, self.best_layout):
            for key in target.keys:
                if key.position_id in state_by_position:
                    char, frozen = state_by_position[key.position_id]
                    key.char = char
                    key.is_frozen = frozen
            # безумовно — стан гарантовано змінився, рахувати дешево
            self.current_score = self._score(self.current_layout)
            self.best_score = self._score(self.best_layout)
            self.tabu.clear()
            self.tabu.append(self._signature(self.current_layout))

    # -----------------------------------------------------------
    # Мутаційні оператори — усі працюють у форматі (list[Key])
    # -----------------------------------------------------------

    def _unfrozen(self, layout: Layout):
        """Return only characters the optimizer is allowed to relocate."""
        return [
            key
            for key in layout.keys
            if key.is_frozen == False and key.char and len(key.char) == 1
        ]

    @staticmethod
    def _require_mutable_keys(keys, required):
        if len(keys) < required:
            raise ValueError(
                f"mutation requires {required} mutable keys; found {len(keys)}"
            )

    def _mutate_single_swap(self, layout: Layout) -> Layout:
        candidate = clone_layout(layout)
        unfrozen = self._unfrozen(candidate)
        self._require_mutable_keys(unfrozen, 2)
        k1, k2 = self.rng.sample(unfrozen, 2)
        k1.char, k2.char = k2.char, k1.char
        return candidate

    def _mutate_segment_shift(self, layout: Layout) -> Layout:
        """3-циклічний зсув: недосяжний одним swap."""
        candidate = clone_layout(layout)
        unfrozen = self._unfrozen(candidate)
        self._require_mutable_keys(unfrozen, 3)
        k1, k2, k3 = self.rng.sample(unfrozen, 3)
        k1.char, k2.char, k3.char = k3.char, k1.char, k2.char
        return candidate

    def _mutate_double_swap(self, layout: Layout) -> Layout:
        """Два незалежні swap за один хід (4 позиції рухаються разом)."""
        candidate = clone_layout(layout)
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

    def reheat_multiplier(self, factor: float | None = None):
        factor = factor if factor is not None else self.reheat_factor
        self.temp = min(self.temp * factor, self.start_temp)

    # button reheat
    def reheat(self, factor: float | None = None):
        """Up the tempeature without loosing best_layout, tabu, history.
            This is not full restart but only out from the stall-plato."""
        print(f'current temp {self.temp}')
        self.reheat_multiplier(factor)
        self.stall_counter = 0

    # -----------------------------------------------------------
    # Основний цикл
    # -----------------------------------------------------------

    def run_optimization(
        self,
        layout: Layout,
        iterations: int = 10000,
        ui_callback: Optional[Callable[..., None]] = None,
    ) -> Layout:
        self.current_layout = copy.deepcopy(layout)
        self.best_layout = copy.deepcopy(layout)
        score = self._score(self.current_layout)

        # debug print layout hash to identify any differences
        a = 'start'
        state_hasher = StateHasher()
        state_hasher(self.current_layout, f"run_optimization.{a} Score from mutator._score(): {score}")

        tabu_hits = 0

        temp = self.temp
        stall_counter = self.stall_counter
        ladder_index = self.ladder_index
        cooling = self.cooling
        accepted_count = self.accepted_count
        improved_count = self.improved_count

        if iterations < 1:
            raise ValueError("iterations must be at least 1")
        self._require_mutable_keys(self._unfrozen(self.current_layout), 2)

        for i in range(1, iterations + 1):

            if self.stop_event is not None and self.stop_event.is_set():
                # debug print layout hash to identify any differences
                a = 'early_exit(stop_event condition)'
                state_hasher(self.current_layout, f"mutator.run_optimization.{a} Score from mutator._score(): {score}")
                break

            candidate = self._apply_mutation(self.current_layout, ladder_index)
            sig = self._signature(candidate)

            if sig in self.tabu:
                # цей стан вже недавно відвідували — пропускаємо ітерацію,
                # без витрати на переоцінку
                tabu_hits += 1
                continue

            candidate_score = self._score(candidate)
            delta = candidate_score - self.current_score

            accepted = False
            if delta < 0:
                accepted = True
            else:
                relative_delta = delta / max(abs(self.current_score), 1.0)
                p = math.exp(-relative_delta / max(temp, 1e-9))
                if self.rng.random() < p:
                    accepted = True

            if accepted:
                accepted_count += 1
                self.current_layout = candidate
                self.current_score = candidate_score
                self.tabu.append(sig)
                if len(self.tabu) > self.tabu_size:
                    self.tabu.pop(0)

            if candidate_score < self.best_score:
                improved_count += 1
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
                    temp = min(temp * self.reheat_factor, self.start_temp)
                    self.history.append({
                        "iter": i, "id": None, "score": self.current_score,
                        "event": f"reheat -> temp={temp:.4f}"
                    })

            self.temp = temp
            self.stall_counter = stall_counter
            self.ladder_index = ladder_index
            self.accepted_count = accepted_count
            self.improved_count = improved_count

            temp *= cooling

            if ui_callback and i % 50 == 0:
                ui_callback(self.best_layout, self.best_score, current_iteration=i)

        # debug print layout hash to identify any differences
        a = 'end_of_the_func post_ui_callback'
        state_hasher(self.current_layout, f"run_optimization.{a} Score from mutator._score(): {score}")

            # debugging prints
            # if i % 100 == 0:
            #     print(f"tabu_hits so far: {tabu_hits}/{i}")
            #     print(f"accepted_count: {self.accepted_count}, improved_count: {self.improved_count}")

            #if i < 10:
            #    print(f"i={i} ... candidate_score={candidate_score} ... self.current_score={self.current_score} ... self.best_score={self.best_score} ... delta={delta}")

        self.engine.update_layout(self.best_layout.keys)
        self.best_layout.score = self.engine.score()
        return copy.deepcopy(self.best_layout)
