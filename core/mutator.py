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
# keep this row for possible debugging process
# from log.loggers.state_hasher import StateHasher

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

        # One long-lived scoring engine for the whole run: the expensive
        # corpus-parsing step (prepare_statistics) happens exactly once here,
        # not on every iteration. Кандидати оцінюються інкрементально
        # (engine.try_layout) відносно поточного стану (engine.load / accept).
        self.engine = scoring.MovementScoringEngine(self.best_layout.keys, moves_config)
        self.engine.prepare_statistics(statistics)

        self.best_score = self._load(self.best_layout)
        self.best_id = str(uuid.uuid4())[:8]
        # Температура калібрується за реальними delta (_calibrate): задаємо
        # імовірність прийняти медіанний погіршувальний swap на початку і після
        # reheat, а в кінці — дрібний (end_quantile) погіршувальний swap.
        self.accept_start = self.config.get("accept_start", 0.5)
        self.accept_end = self.config.get("accept_end", 0.001)
        self.accept_reheat = self.config.get("accept_reheat", 0.1)
        self.end_quantile = self.config.get("end_quantile", 0.1)
        self.calibration_samples = self.config.get("calibration_samples", 200)
        self.stall_window = self.config.get("stall_window", 300)
        self.restart_window = self.config.get("restart_window", 2000)
        self.tabu_size = self.config.get("tabu_size", 50)
        if not 0 < self.accept_end < 1 or not 0 < self.accept_reheat <= self.accept_start < 1:
            raise ValueError("need 0 < accept_end < 1 and 0 < accept_reheat <= accept_start < 1")
        if not 0 <= self.end_quantile <= 0.5:
            raise ValueError("end_quantile must be within [0, 0.5]")
        if self.stall_window <= 0 or self.restart_window <= 0 or self.tabu_size < 0:
            raise ValueError("stall/restart windows must be positive and tabu_size cannot be negative")
        self.rng = random.Random(self.config.get("seed", 42))

        # поточний "робочий" стан SA (окремо від best — SA інколи стоїть
        # на гіршому за best стані, це механізм проти цугцвангу)
        self.current_layout = copy.deepcopy(initial_layout)
        self.current_score = self.best_score

        self.history = [{"iter": 0, "id": self.best_id, "score": self.best_score, "event": "seed"}]
        self.tabu = [self._signature(self.current_layout)]

        # для основного циклу оптимізації
        self.stall_counter = 0  # ітерацій без покращення best
        self.ladder_index = 0  # чим він більше, тим масштабніша мутація (0 = swap двох клавіш, 1 = потрійна перестановка, 2 = подвійний swap)
        # температури (відносна delta, див. run_optimization); None — ще не
        # калібровано, це робить перший run_optimization
        self.start_temp: Optional[float] = None
        self.end_temp: Optional[float] = None
        self.reheat_temp: Optional[float] = None
        self.temp: Optional[float] = None  # поточна; чим вища, тим легше прийняти гірший стан
        self.accepted_count = 0  # лічильник прийнятих станів
        self.improved_count = 0  # лічильник покращених станів
        # запит на reheat з UI-потоку; цикл забирає його на початку ітерації,
        # інакше локальна temp у run_optimization перетерла б зміну
        self._pending_reheat: Optional[float] = None

    # access to current layout keys
    @property
    def keys(self) -> List[Key]:
        return self.current_layout.keys

    # -----------------------------------------------------------
    # Sync UI-side edits (e.g. freeze toggles made while paused)
    # -----------------------------------------------------------

    def _load(self, layout: Layout) -> float:
        """Повна оцінка; layout стає базою для engine.try_layout."""
        return self.engine.load(layout.keys)

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
            # безумовно — стан гарантовано змінився; current — останнім,
            # бо він база для delta-оцінки
            self.best_score = self._load(self.best_layout)
            self.current_score = self._load(self.current_layout)
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

    # Мутації змінюють layout на місці й повертають undo — список
    # (key, старий char) для _undo, щоб не клонувати розкладку щоітерації.

    def _mutate_single_swap(self, layout: Layout):
        unfrozen = self._unfrozen(layout)
        self._require_mutable_keys(unfrozen, 2)
        k1, k2 = self.rng.sample(unfrozen, 2)
        undo = [(k1, k1.char), (k2, k2.char)]
        k1.char, k2.char = k2.char, k1.char
        return undo

    def _mutate_segment_shift(self, layout: Layout):
        """3-циклічний зсув: недосяжний одним swap."""
        unfrozen = self._unfrozen(layout)
        self._require_mutable_keys(unfrozen, 3)
        k1, k2, k3 = self.rng.sample(unfrozen, 3)
        undo = [(k1, k1.char), (k2, k2.char), (k3, k3.char)]
        k1.char, k2.char, k3.char = k3.char, k1.char, k2.char
        return undo

    def _mutate_double_swap(self, layout: Layout):
        """Два незалежні swap за один хід (4 позиції рухаються разом)."""
        unfrozen = self._unfrozen(layout)
        self._require_mutable_keys(unfrozen, 4)
        k1, k2, k3, k4 = self.rng.sample(unfrozen, 4)
        undo = [(k1, k1.char), (k2, k2.char), (k3, k3.char), (k4, k4.char)]
        k1.char, k2.char = k2.char, k1.char
        k3.char, k4.char = k4.char, k3.char
        return undo

    @staticmethod
    def _undo(undo) -> None:
        for key, char in undo:
            key.char = char

    MUTATION_LADDER_NAMES = ["single_swap", "segment_shift", "double_swap"]

    def _apply_mutation(self, layout: Layout, ladder_index: int):
        fn = [self._mutate_single_swap, self._mutate_segment_shift, self._mutate_double_swap]
        mutable_count = len(self._unfrozen(layout))
        max_ladder_index = 2 if mutable_count >= 4 else 1 if mutable_count >= 3 else 0
        fn = fn[min(ladder_index, max_ladder_index)]
        return fn(layout)

    def _signature(self, layout: Layout):
        """Компактний підпис стану для tabu-списку (порядок char по позиціях)."""
        return tuple(k.char for k in layout.keys)

    def _calibrate(self, layout: Layout) -> None:
        """Температури з реального масштабу delta: розподіл відносного
        погіршення від випадкових swap навколо layout. T = d / ln(1/p) дає
        імовірність p прийняти погіршення d. Старт і reheat — за медіаною,
        кінець — за дрібним погіршенням (end_quantile), щоб наприкінці
        прогону SA фактично дотюнював жадібно."""
        base = self._load(layout)
        worse = []
        for _ in range(self.calibration_samples):
            undo = self._mutate_single_swap(layout)
            delta = self.engine.try_layout(layout.keys) - base
            self._undo(undo)
            if delta > 0:
                worse.append(delta / max(abs(base), 1.0))
        worse.sort()
        median = worse[len(worse) // 2] if worse else 1e-3
        small = worse[int(len(worse) * self.end_quantile)] if worse else 1e-4
        self.start_temp = median / math.log(1 / self.accept_start)
        self.end_temp = min(small / math.log(1 / self.accept_end), self.start_temp)
        self.reheat_temp = median / math.log(1 / self.accept_reheat)
        self.temp = self.start_temp
        self.history.append({
            "iter": 0, "id": None, "score": base,
            "event": f"calibrate: median worse {median:.4f}, small {small:.4f} -> temp {self.start_temp:.5f}..{self.end_temp:.6f}"
        })

    # button reheat
    def reheat(self, factor: float | None = None):
        """Up the tempeature without loosing best_layout, tabu, history.
            This is not full restart but only out from the stall-plato.
            factor — множник до reheat_temp (за замовчуванням 1).
            Safe to call from another thread: the request is applied by
            run_optimization at the start of its next iteration."""
        self._pending_reheat = factor if factor is not None else 1.0

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
        # delta і порівняння з best мають рахуватися від переданого layout,
        # а не від score, що залишився з __init__ / попереднього запуску
        self.current_score = self.best_score = self._load(self.current_layout)

        # state_hasher(self.current_layout, f"run_optimization.{a} Score from mutator._score(): {self.current_score}")

        tabu_hits = 0

        if iterations < 1:
            raise ValueError("iterations must be at least 1")
        self._require_mutable_keys(self._unfrozen(self.current_layout), 2)

        # перший запуск калібрує і стартує з start_temp; продовження після
        # Stop/Start тягне температуру далі до end_temp за новий прогін
        if self.temp is None:
            self._calibrate(self.current_layout)
        elif self.temp < self.reheat_temp:
            # попередній прогін (майже) дохолов — новий почнеться з reheat,
            # а не жадібно біля end_temp
            self.temp = self.reheat_temp
        temp = self.temp
        cooling = (self.end_temp / temp) ** (1 / iterations) if temp > self.end_temp else 1.0
        stall_counter = self.stall_counter
        ladder_index = self.ladder_index
        accepted_count = self.accepted_count
        improved_count = self.improved_count

        for i in range(1, iterations + 1):

            if self.stop_event is not None and self.stop_event.is_set():
                break

            factor, self._pending_reheat = self._pending_reheat, None
            if factor is not None:
                temp = min(self.reheat_temp * factor, self.start_temp)
                stall_counter = 0
                self.history.append({
                    "iter": i, "id": None, "score": self.current_score,
                    "event": f"manual reheat -> temp={temp:.5f}"
                })

            # кандидат — current_layout після мутації на місці; якщо його не
            # прийнято, _undo повертає current_layout назад
            undo = self._apply_mutation(self.current_layout, ladder_index)
            sig = self._signature(self.current_layout)

            if sig in self.tabu:
                # цей стан вже недавно відвідували — пропускаємо ітерацію,
                # без витрати на переоцінку
                self._undo(undo)
                tabu_hits += 1
                continue

            candidate_score = self.engine.try_layout(self.current_layout.keys)
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
                self.engine.accept()
                self.current_score = candidate_score
                self.tabu.append(sig)
                if len(self.tabu) > self.tabu_size:
                    self.tabu.pop(0)

            if candidate_score < self.best_score:
                improved_count += 1
                # покращення best завжди прийняте (candidate < best <= current)
                self.best_layout = clone_layout(self.current_layout)
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

            if not accepted:
                self._undo(undo)

            if stall_counter > 0 and stall_counter % self.stall_window == 0:
                mutable_count = len(self._unfrozen(self.current_layout))
                max_ladder_index = 2 if mutable_count >= 4 else 1 if mutable_count >= 3 else 0
                if ladder_index < max_ladder_index:
                    ladder_index += 1
                    self.history.append({
                        "iter": i, "id": None, "score": self.current_score,
                        "event": f"escalate -> {self.MUTATION_LADDER_NAMES[ladder_index]}"
                    })
            if stall_counter >= self.restart_window:
                # довгий застій: повернення до best — шукаємо інший шлях від
                # найкращого стану, а не блукаємо від поточного. Reheat лише в
                # першій половині прогону: пізніше не встигне охолонути.
                self.current_layout = copy.deepcopy(self.best_layout)
                self.current_score = self._load(self.current_layout)
                if i < iterations // 2:
                    temp = max(temp, self.reheat_temp)
                stall_counter = 0
                ladder_index = 0
                self.history.append({
                    "iter": i, "id": None, "score": self.current_score,
                    "event": f"restart from best, reheat -> temp={temp:.5f}"
                })

            self.temp = temp
            self.stall_counter = stall_counter
            self.ladder_index = ladder_index
            self.accepted_count = accepted_count
            self.improved_count = improved_count

            temp = max(temp * cooling, self.end_temp)

            if ui_callback and i % 50 == 0:
                ui_callback(self.best_layout, self.best_score, current_iteration=i)

            #     print(f"accepted_count: {self.accepted_count}, improved_count: {self.improved_count}")

            #if i < 10:
            #    print(f"i={i} ... candidate_score={candidate_score} ... self.current_score={self.current_score} ... self.best_score={self.best_score} ... delta={delta}")

        self.engine.update_layout(self.best_layout.keys)
        self.best_layout.score = self.engine.score()
        return copy.deepcopy(self.best_layout)
