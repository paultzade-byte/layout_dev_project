"""Config-driven movement scoring for keyboard layouts.

The scorer detects events from physical keys and applies the numeric policy in
``config/moves.yaml``.  Lower scores represent easier layouts.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np

import yaml

from core.models import Finger, Key, Layout, ScoreMetrics


_REQUIRED_MOVES_SCHEMA = {
    "base_effort": {
        "row_multiplier": ("top", "home", "bottom", "other"),
        "finger_multiplier": ("pinky", "ring", "middle", "index", "thumb"),
    },
    "same_finger": ("double_tap", "adjacent_row", "skip_row"),
    "shape_multiplier": ("vertical", "diagonal", "horizontal"),
    "roll": ("inward", "outward", "awkward"),
    "hand": ("alternation", "strict_alternation"),
}


def load_moves_config(path: str | Path) -> Dict[str, Any]:
    """Load and validate the numeric movement-policy YAML file."""
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    return validate_moves_config(config)


def validate_moves_config(config: Any) -> Dict[str, Any]:
    """Reject incomplete or non-numeric policies before scoring starts."""
    if not isinstance(config, dict) or config.get("version") != 1:
        raise ValueError("moves config must be a mapping with version: 1")

    for section, required in _REQUIRED_MOVES_SCHEMA.items():
        value = config.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"moves config section '{section}' must be a mapping")

        if isinstance(required, dict):
            for subsection, names in required.items():
                nested = value.get(subsection)
                if not isinstance(nested, dict):
                    raise ValueError(
                        f"moves config section '{section}.{subsection}' must be a mapping"
                    )
                _validate_numeric_values(nested, names, f"{section}.{subsection}")
        else:
            _validate_numeric_values(value, required, section)

    return config


def _validate_numeric_values(values: Dict[str, Any], names: Tuple[str, ...], path: str) -> None:
    for name in names:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"moves config value '{path}.{name}' must be numeric")


def calculate_total_penalty(
    layout: Layout,
    statistics: Dict[str, Any],
    moves_config: Dict[str, Any] | None = None,
) -> float:
    """Compatibility entry point for callers that need only the total score."""
    if moves_config is None:
        moves_config = load_moves_config(
            Path(__file__).resolve().parents[1] / "config" / "moves.yaml"
        )
    # return the class object and here it could be created
    return MovementScoringEngine(layout.keys, moves_config).score_from_statistics(statistics).total_penalty


class MovementScoringEngine:
    def __init__(self, layout_keys: List[Key], moves_config: Dict[str, Any]):
        self.char_map: Dict[str, Key] = {
            key.char: key for key in layout_keys if key.char
        }
        self.moves = validate_moves_config(moves_config)

        # static massives preparation
        # список символів у фіксованому порядку -> індекс
        self.chars = list(self.char_map.keys())
        self.char_to_idx = {c: i for i, c in enumerate(self.chars)}

        n = len(self.chars)
        self.row = np.array([self.char_map[c].row for c in self.chars])
        self.col = np.array([self.char_map[c].col for c in self.chars])
        self.hand = np.array([self.char_map[c].hand.value for c in self.chars])
        self.finger = np.array([self.char_map[c].finger.value for c in self.chars])
        self.base_cost = np.array([self.char_map[c].base_cost for c in self.chars])


    def prepare_bigram_array(self, bigrams: dict):
        # called once when statistics are importing than it becomes cached
        idx1, idx2, weight = [], [], []
        for bg, freq in bigrams.items():
            if bg[0] in self.char_to_idx and bg[1] in self.char_to_idx:
                idx1.append(self.char_to_idx[bg[0]])
                idx2.append(self.char_to_idx[bg[1]])
                weight.append(freq)
        return np.array(idx1), np.array(idx2), np.array(weight, dtype=float)

    def prepare_trigram_array(self, trigrams: dict):
        idx1, idx2, idx3, weight = [], [], [], []
        for tg, freq in trigrams.items():
            if tg[0] in self.char_to_idx and tg[1] in self.char_to_idx and tg[2] in self.char_to_idx:
                idx1.append(self.char_to_idx[tg[0]])
                idx2.append(self.char_to_idx[tg[1]])
                idx3.append(self.char_to_idx[tg[2]])
                weight.append(freq)
        return np.array(idx1), np.array(idx2), np.array(idx3), np.array(weight, dtype=float)

    def _evaluate_unigrams(self, statistics, metrics):
        for char, freq in statistics.get('unigrams', {}).items():
            key = self.char_map.get(char)
            if key is None:
                continue
            metrics.base_effort += key.base_cost * self._base_effort_multiplier(key) * freq

    def _evaluate_bigrams_vectorized(self, idx1, idx2, weight, metrics):
        hand1, hand2 = self.hand[idx1], self.hand[idx2]
        finger1, finger2 = self.finger[idx1], self.finger[idx2]
        row1, row2 = self.row[idx1], self.row[idx2]
        col1, col2 = self.col[idx1], self.col[idx2]

        same_hand = hand1 == hand2
        same_finger = same_hand & (finger1 == finger2)
        diff_finger_same_hand = same_hand & ~same_finger

        # alternation bonus (різні руки)
        alternation_mask = ~same_hand
        metrics.alternation_bonus += np.sum(
            weight[alternation_mask] * self.moves["hand"]["alternation"]
        )

        # серед same_finger - рахуємо row_difference і shape
        row_diff = np.abs(row1[same_finger] - row2[same_finger])
        # shape: vertical/horizontal/diagonal через col/row порівняння
        same_row = row1[same_finger] == row2[same_finger]
        same_col = col1[same_finger] == col2[same_finger]
        shape_mult = np.where(
            same_row, self.moves["shape_multiplier"]["horizontal"],
            np.where(same_col, self.moves["shape_multiplier"]["vertical"],
                self.moves["shape_multiplier"]["diagonal"])
        )
        finger_mult = self._finger_multiplier_array(finger1[same_finger])
        w_sf = weight[same_finger]
        mult = shape_mult * finger_mult

        double_tap_mask = row_diff == 0
        adjacent_mask = row_diff == 1
        skip_mask = row_diff >= 2

        metrics.double_tap_penalty += np.sum(
            w_sf[double_tap_mask] * mult[double_tap_mask] * self.moves["same_finger"]["double_tap"]
        )
        metrics.sfb_penalty += np.sum(
            w_sf[adjacent_mask] * mult[adjacent_mask] * self.moves["same_finger"]["adjacent_row"]
        )
        metrics.sfs_penalty += np.sum(
            w_sf[skip_mask] * mult[skip_mask] * self.moves["same_finger"]["skip_row"]
        )

    def _evaluate_trigrams_vectorized(self, idx1, idx2, idx3, weight, metrics):
        hand1, hand2, hand3 = self.hand[idx1], self.hand[idx2], self.hand[idx3]
        finger1, finger2, finger3 = self.finger[idx1], self.finger[idx2], self.finger[idx3]

        # strict alternation: hand1==hand3, hand1 != hand2  (ABA pattern)
        strict_alt_mask = (hand1 == hand3) & (hand1 != hand2)
        metrics.strict_alternation_penalty += np.sum(
            weight[strict_alt_mask] * self.moves["hand"]["strict_alternation"]
        )

        # same-hand triples only (усі три на одній руці)
        same_hand_mask = (hand1 == hand2) & (hand2 == hand3) & ~strict_alt_mask
        f1, f2, f3 = finger1[same_hand_mask], finger2[same_hand_mask], finger3[same_hand_mask]
        w = weight[same_hand_mask]

        inward_mask = (f1 <= f2) & (f2 <= f3) & ((f1 != f2) | (f2 != f3))
        outward_mask = (f1 >= f2) & (f2 >= f3) & ((f1 != f2) | (f2 != f3))
        awkward_mask = ((f1 < f2) & (f2 > f3)) | ((f1 > f2) & (f2 < f3))

        metrics.oht_inward_penalty += np.sum(w[inward_mask] * self.moves["roll"]["inward"])
        metrics.oht_outward_penalty += np.sum(w[outward_mask] * self.moves["roll"]["outward"])
        metrics.oht_awkward_penalty += np.sum(w[awkward_mask] * self.moves["roll"]["awkward"])

    def _evaluate_skipgrams_vectorized(self, idx1, idx2, weight, metrics):
        hand1, hand2 = self.hand[idx1], self.hand[idx2]
        finger1, finger2 = self.finger[idx1], self.finger[idx2]

        same_hand = hand1 == hand2
        same_finger = same_hand & (finger1 == finger2)

        metrics.skipgram_same_finger_penalty += np.sum(
            weight[same_finger] * self.moves.get("skip_bigram", {}).get("same_finger", 1.0)
        )
        metrics.skipgram_same_hand_penalty += np.sum(
            weight[same_hand & ~same_finger] * self.moves.get("skip_bigram", {}).get("same_hand", 0.1)
        )

    #########################################################################
    def score_from_statistics(self, statistics: Dict[str, Any]) -> ScoreMetrics:
        metrics = ScoreMetrics()

        # unigrams - поки лишаємо як є (дешево, або теж векторизуй окремо)
        for char, freq in statistics.get("unigrams", {}).items():
            key = self.char_map.get(char)
            if key is None:
                continue
            metrics.base_effort += key.base_cost * self._base_effort_multiplier(key) * freq

        # bigrams - збираємо ВСІ idx/weights одразу, викликаємо evaluate ОДИН раз
        idx1, idx2, weights = self._prepare_pair_arrays(statistics.get("bigrams", {}), n=2)
        if len(idx1) > 0:
            self._evaluate_bigrams_vectorized(idx1, idx2, weights, metrics)

        # trigrams
        t1, t2, t3, tw = self._prepare_triple_arrays(statistics.get("trigrams", {}))
        if len(t1) > 0:
            self._evaluate_trigrams_vectorized(t1, t2, t3, tw, metrics)

        # skipgrams
        s1, s2, sw = self._prepare_pair_arrays(statistics.get("skipgrams", {}), n=2)
        if len(s1) > 0:
            self._evaluate_skipgrams_vectorized(s1, s2, sw, metrics)

        metrics.total_penalty = sum((
            metrics.base_effort, metrics.sfb_penalty, metrics.sfs_penalty,
            metrics.double_tap_penalty, metrics.oht_inward_penalty,
            metrics.oht_outward_penalty, metrics.oht_awkward_penalty,
            metrics.strict_alternation_penalty, metrics.alternation_bonus,
            metrics.skipgram_same_finger_penalty, metrics.skipgram_same_hand_penalty,
        ))
        return metrics

    def _prepare_pair_arrays(self, pairs: Dict[str, float], n: int):
        idx1, idx2, w = [], [], []
        for pair, freq in pairs.items():
            if len(pair) != n:
                continue
            i1 = self.char_to_idx.get(pair[0])
            i2 = self.char_to_idx.get(pair[1])
            if i1 is None or i2 is None:
                continue
            idx1.append(i1)
            idx2.append(i2)
            w.append(freq)
        return np.array(idx1), np.array(idx2), np.array(w, dtype=float)

    def _prepare_triple_arrays(self, triples: Dict[str, float]):
        idx1, idx2, idx3, w = [], [], [], []
        for tri, freq in triples.items():
            if len(tri) != 3:
                continue
            i1 = self.char_to_idx.get(tri[0])
            i2 = self.char_to_idx.get(tri[1])
            i3 = self.char_to_idx.get(tri[2])
            if i1 is None or i2 is None or i3 is None:
                continue
            idx1.append(i1); idx2.append(i2); idx3.append(i3)
            w.append(freq)
        return np.array(idx1), np.array(idx2), np.array(idx3), np.array(w, dtype=float)

    def _base_effort_multiplier(self, key: Key) -> float:
        row_name = self.get_row_name(key.row)
        row_weight = self.moves["base_effort"]["row_multiplier"].get(
            row_name, self.moves["base_effort"]["row_multiplier"]["other"]
        )
        return row_weight * self._finger_multiplier(key.finger)  # скалярна, не _array

    def _finger_multiplier(self, finger: Finger) -> float:
        """Скалярна версія — для одиночного Key (unigram-цикл)."""
        return self.moves["base_effort"]["finger_multiplier"][
            self._get_finger_name(finger)
        ]

    def _finger_multiplier_array(self, finger_values: np.ndarray) -> np.ndarray:
        """Векторизована версія — для масиву finger-значень (bigram/trigram)."""
        lookup = self.moves["base_effort"]["finger_multiplier"]
        return np.array([lookup[self._get_finger_name(f)] for f in finger_values])
        """
    def _finger_multiplier_array(self, finger_values: np.ndarray) -> np.ndarray:
        #Векторизована версія _finger_multiplier: масив Finger.value -> масив множників.
        # мапа Finger.value -> назва (той самий порядок, що в _get_finger_name)
        finger_names = {
            Finger.PINKY.value: "pinky",
            Finger.RING.value: "ring",
            Finger.MIDDLE.value: "middle",
            Finger.INDEX.value: "index",
            Finger.THUMB.value: "thumb",
        }
        lookup = self.moves["base_effort"]["finger_multiplier"]
        # будуємо масив значень через vectorized mapping
        return np.array([lookup[finger_names[f]] for f in finger_values])
        """
    @staticmethod
    def get_row_name(row_index: int) -> str:
        return {0: "top", 1: "home", 2: "bottom"}.get(row_index, "other")

    @staticmethod
    def _get_shape(k1: Key, k2: Key) -> str:
        if k1.row == k2.row:
            return "horizontal"
        if k1.col == k2.col:
            return "vertical"
        return "diagonal"

    @staticmethod
    def _get_finger_name(finger_value) -> str:
        if isinstance(finger_value, Finger):
            finger_value = finger_value.value
        return {
            Finger.PINKY.value: "pinky",
            Finger.RING.value: "ring",
            Finger.MIDDLE.value: "middle",
            Finger.INDEX.value: "index",
            Finger.THUMB.value: "thumb",
            }[int(finger_value)]
