"""Config-driven movement scoring for keyboard layouts.

The scorer detects events from physical keys and applies the numeric policy in
``config/moves.yaml``.  Lower scores represent easier layouts.

PERFORMANCE NOTE
-----------------
There are two very different costs hiding in this file:

1. Turning the statistics dict (``config/statistic.json`` — thousands of
   bigrams/trigrams/skipgrams) into index arrays. This is a pure-Python loop
   over the whole corpus and is *expensive*. It only needs to happen ONCE per
   optimization run, because the statistics never change while SA is running.

2. Reading the *current* position/hand/finger of every character. This is
   cheap (O(number of characters), ~30-40), because it only touches the
   layout, not the corpus. It has to happen on every mutation, because that's
   exactly what a mutation changes.

The old version mixed these two together inside ``score_from_statistics`` and
``calculate_total_penalty`` (called fresh every SA iteration), so cost #1 was
being paid on every single iteration instead of once. That's what made NumPy
vectorization a no-op in practice: the vectorized math was fast, but it was
preceded by a full corpus-sized Python loop every time.

``MovementScoringEngine`` now exposes:

- ``prepare_statistics(statistics)`` — call once, does the expensive part.
- ``update_layout(layout_keys)`` — call on every mutation, cheap.
- ``score()`` — pure NumPy, uses whatever was cached by the two calls above.

``score_from_statistics(statistics)`` and ``calculate_total_penalty(...)`` are
kept as slow, self-contained convenience wrappers for one-off scoring (tests,
scripts) — they rebuild everything from scratch every call, same as before.
Do NOT use them inside a hot loop.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
    """Slow, self-contained one-off scorer. Rebuilds everything from scratch.

    Fine for tests/scripts/one-shot calls. Do NOT call this inside an SA loop —
    use a single long-lived ``MovementScoringEngine`` with ``prepare_statistics``
    + ``update_layout`` + ``score`` instead (see ``LayoutOptimizerSA``).
    """
    if moves_config is None:
        moves_config = load_moves_config(
            Path(__file__).resolve().parents[1] / "config" / "moves.yaml"
        )
    engine = MovementScoringEngine(layout.keys, moves_config)
    engine.prepare_statistics(statistics)
    return engine.score().total_penalty


class MovementScoringEngine:
    def __init__(self, layout_keys: List[Key], moves_config: Dict[str, Any]):
        self.moves = validate_moves_config(moves_config)

        # Vocabulary: the SET of chars never changes during optimization —
        # only WHICH position each char sits at changes. So the char->index
        # mapping is fixed for the engine's whole lifetime.
        self.chars = [key.char for key in layout_keys if key.char]
        self.char_to_idx = {c: i for i, c in enumerate(self.chars)}
        n = len(self.chars)

        # Per-char geometry arrays. These DO depend on current positions,
        # so they get refreshed by update_layout() — cheaply (O(n) here).
        self.row = np.empty(n, dtype=np.int64)
        self.col = np.empty(n, dtype=np.int64)
        self.hand = np.empty(n, dtype=object)
        self.finger = np.empty(n, dtype=np.int64)
        self.base_cost = np.empty(n, dtype=np.float64)

        # Small lookup tables derived from moves_config only (never change).
        finger_mult = self.moves["base_effort"]["finger_multiplier"]
        # index by Finger.value (1..5); index 0 unused.
        self._finger_mult_by_value = np.zeros(6, dtype=np.float64)
        for finger in Finger:
            self._finger_mult_by_value[finger.value] = finger_mult[
                self._get_finger_name(finger.value)
            ]

        self.update_layout(layout_keys)

        # Statistics-derived index arrays — expensive to build, so they are
        # cached and only rebuilt when prepare_statistics() is called again.
        self._bigram_idx: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._trigram_idx: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None
        self._skipgram_idx: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._unigram_idx: Optional[np.ndarray] = None
        self._unigram_weight: Optional[np.ndarray] = None
        self._statistics_prepared = False

    # -----------------------------------------------------------
    # Expensive, one-time-per-run setup
    # -----------------------------------------------------------

    def prepare_statistics(self, statistics: Dict[str, Any]) -> "MovementScoringEngine":
        """Convert the statistics dict into cached index arrays.

        This is the part that walks the whole corpus (thousands of entries)
        with a plain Python loop, so it is deliberately NOT called from
        update_layout()/score(). Call it once per optimization run (or
        whenever the statistics themselves change, which they don't during
        a single SA run).
        """
        self._bigram_idx = self._prepare_pair_arrays(statistics.get("bigrams", {}))
        self._trigram_idx = self._prepare_triple_arrays(statistics.get("trigrams", {}))
        self._skipgram_idx = self._prepare_pair_arrays(statistics.get("skipgrams", {}))

        uni_idx, uni_w = [], []
        for char, freq in statistics.get("unigrams", {}).items():
            i = self.char_to_idx.get(char)
            if i is None:
                continue
            uni_idx.append(i)
            uni_w.append(freq)
        self._unigram_idx = np.array(uni_idx, dtype=np.int64)
        self._unigram_weight = np.array(uni_w, dtype=np.float64)

        self._statistics_prepared = True
        return self

    def _prepare_pair_arrays(self, pairs: Dict[str, float]):
        idx1, idx2, w = [], [], []
        for pair, freq in pairs.items():
            if len(pair) != 2:
                continue
            i1 = self.char_to_idx.get(pair[0])
            i2 = self.char_to_idx.get(pair[1])
            if i1 is None or i2 is None:
                continue
            idx1.append(i1)
            idx2.append(i2)
            w.append(freq)
        return np.array(idx1, dtype=np.int64), np.array(idx2, dtype=np.int64), np.array(w, dtype=np.float64)

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
        return (
            np.array(idx1, dtype=np.int64), np.array(idx2, dtype=np.int64),
            np.array(idx3, dtype=np.int64), np.array(w, dtype=np.float64),
        )

    # -----------------------------------------------------------
    # Cheap, per-mutation update
    # -----------------------------------------------------------

    def update_layout(self, layout_keys: List[Key]) -> "MovementScoringEngine":
        """Refresh per-char geometry after a mutation. O(number of chars).

        IMPORTANT: the set of chars in ``layout_keys`` must be exactly the
        vocabulary this engine was built with — mutations may move chars
        between positions, but must not introduce or remove chars.
        """
        char_map = {key.char: key for key in layout_keys if key.char}
        for char, idx in self.char_to_idx.items():
            key = char_map[char]
            self.row[idx] = key.row
            self.col[idx] = key.col
            self.hand[idx] = key.hand.value
            self.finger[idx] = key.finger.value
            self.base_cost[idx] = key.base_cost
        return self

    # -----------------------------------------------------------
    # Scoring — pure NumPy, no Python-level loop over the corpus
    # -----------------------------------------------------------

    def score(self) -> ScoreMetrics:
        """Fast path: score the layout currently loaded via update_layout(),
        against the statistics currently cached via prepare_statistics().
        """
        if not self._statistics_prepared:
            raise RuntimeError(
                "prepare_statistics() must be called at least once before score()"
            )

        metrics = ScoreMetrics()

        self._evaluate_unigrams_vectorized(metrics)

        idx1, idx2, weight = self._bigram_idx
        if len(idx1) > 0:
            self._evaluate_bigrams_vectorized(idx1, idx2, weight, metrics)

        t1, t2, t3, tw = self._trigram_idx
        if len(t1) > 0:
            self._evaluate_trigrams_vectorized(t1, t2, t3, tw, metrics)

        s1, s2, sw = self._skipgram_idx
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

    def score_from_statistics(self, statistics: Dict[str, Any]) -> ScoreMetrics:
        """Slow, self-contained convenience path for one-off calls (tests,
        scripts). Re-does the expensive statistics prep every call — do not
        use this inside the SA loop.
        """
        self.prepare_statistics(statistics)
        return self.score()

    def _evaluate_unigrams_vectorized(self, metrics: ScoreMetrics) -> None:
        idx = self._unigram_idx
        if idx is None or len(idx) == 0:
            return
        weight = self._unigram_weight
        row = self.row[idx]
        finger = self.finger[idx]
        base_cost = self.base_cost[idx]

        row_cfg = self.moves["base_effort"]["row_multiplier"]
        row_weight = np.select(
            [row == 0, row == 1, row == 2],
            [row_cfg["top"], row_cfg["home"], row_cfg["bottom"]],
            default=row_cfg["other"],
        )
        finger_weight = self._finger_mult_by_value[finger]

        metrics.base_effort += float(np.sum(base_cost * row_weight * finger_weight * weight))

    def _evaluate_bigrams_vectorized(self, idx1, idx2, weight, metrics):
        hand1, hand2 = self.hand[idx1], self.hand[idx2]
        finger1, finger2 = self.finger[idx1], self.finger[idx2]
        row1, row2 = self.row[idx1], self.row[idx2]
        col1, col2 = self.col[idx1], self.col[idx2]

        same_hand = hand1 == hand2
        same_finger = same_hand & (finger1 == finger2)

        # alternation bonus (різні руки)
        alternation_mask = ~same_hand
        metrics.alternation_bonus += np.sum(
            weight[alternation_mask] * self.moves["hand"]["alternation"]
        )

        # серед same_finger - рахуємо row_difference і shape
        row_diff = np.abs(row1[same_finger] - row2[same_finger])
        same_row = row1[same_finger] == row2[same_finger]
        same_col = col1[same_finger] == col2[same_finger]
        shape_mult = np.where(
            same_row, self.moves["shape_multiplier"]["horizontal"],
            np.where(same_col, self.moves["shape_multiplier"]["vertical"],
                self.moves["shape_multiplier"]["diagonal"])
        )
        finger_mult = self._finger_mult_by_value[finger1[same_finger]]
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

    @staticmethod
    def get_row_name(row_index: int) -> str:
        return {0: "top", 1: "home", 2: "bottom"}.get(row_index, "other")

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
