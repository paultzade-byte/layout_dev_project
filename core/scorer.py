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
        "row_multiplier": ("top", "home_row", "bottom", "other"),
        "finger_multiplier": ("pinky", "ring", "middle", "index", "thumb"),
        "column_multiplier": ("home_col", "col"),
    },
    # None = числовий лист; tuple = вкладена секція з числовими листами
    "same_finger": {
        "same_key": None,
        "lateral": None,
        "diagonal_down": None,
        "diagonal_up": None,
        "vertical": None,
        "skip_row": {
            "max": None,
            "ratio": ("pinky", "ring", "middle", "index"),
        },
    },
    "roll": ("inward", "outward", "awkward"),
    "roll_rows": ("natural_arc", "bottom_step", "row_skip", "drop_jump"),
    "hand": ("left_mult", "right_mult"),
    "hand_runs": ("single", "balanced", "overload", "overload_step"),
    "finger_alternation": (
            "brother_finger", "nextdoor_finger", "foreign_finger",
            "ring_pinky_crash", "thumb_mult",
        ),
}

_FINGER_PAIR_CATEGORY = {
    frozenset({Finger.RING.value, Finger.MIDDLE.value }): "brother_finger",
    frozenset({Finger.MIDDLE.value, Finger.INDEX.value }): "brother_finger",
    frozenset({Finger.PINKY.value, Finger.MIDDLE.value }): "nextdoor_finger",
    frozenset({Finger.RING.value, Finger.INDEX.value }): "nextdoor_finger",
    frozenset({Finger.PINKY.value, Finger.INDEX.value }): "foreign_finger",
    frozenset({Finger.PINKY.value, Finger.RING.value }): "ring_pinky_crash",

}
def load_moves_config(path: str | Path, adjusted: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Load and validate the numeric movement-policy YAML file.
       Merge overrides and validate again."""
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    config = validate_moves_config(config)
    if adjusted:
        config = merge_config(config, adjusted)
        config = validate_moves_config(config)
    return config


def validate_moves_config(config: Any) -> Dict[str, Any]:
    """Reject incomplete or non-numeric policies before scoring starts."""
    if not isinstance(config, dict) or config.get("version") != 1:
        raise ValueError("moves config must be a mapping with version: 1")

    _validate_section(config, _REQUIRED_MOVES_SCHEMA, "")
    return config


def _validate_section(value: Any, spec: Any, path: str) -> None:
    """spec: dict -> секція з іменованими полями, tuple -> секція з числовими
    листами, None -> одне числове значення."""
    if spec is None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"moves config value '{path}' must be numeric")
        return
    if not isinstance(value, dict):
        raise ValueError(f"moves config section '{path}' must be a mapping")
    if isinstance(spec, tuple):
        _validate_numeric_values(value, spec, path)
        return
    for name, sub_spec in spec.items():
        _validate_section(value.get(name), sub_spec, f"{path}.{name}" if path else name)

# recursive merge
def merge_config(config: Dict[str, Any], adjusted: Dict[str, Any]) -> Dict[str, Any]:
    updated_config = config.copy()
    for key, value in adjusted.items():
        if isinstance(value,dict) and isinstance(updated_config.get(key), dict):
            updated_config[key] = merge_config(updated_config[key], value)
        else:
            updated_config[key] = value
    return updated_config

def _validate_numeric_values(values: Dict[str, Any], names: Tuple[str, ...], path: str) -> None:
    for name in names:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"moves config value '{path}.{name}' must be numeric")

def calculate_total_penalty(
    layout: Layout,
    statistics: Dict[str, Any],
    moves_config: Optional[Dict[str, Any]] = None,
    adjusted: Optional[Dict] = None,
) -> float:
    """Slow, self-contained one-off scorer. Rebuilds everything from scratch.

    Fine for tests/scripts/one-shot calls. Do NOT call this inside an SA loop —
    use a single long-lived ``MovementScoringEngine`` with ``prepare_statistics``
    + ``update_layout`` + ``score`` instead (see ``LayoutOptimizerSA``).
    """
    if moves_config is None:
        moves_config = load_moves_config(
            Path(__file__).resolve().parents[1] / "config" / "moves.yaml",
            adjusted
        )
    engine = MovementScoringEngine(layout.keys, moves_config)
    engine.prepare_statistics(statistics)
    return engine.score().total_penalty / 1000000000


class MovementScoringEngine:
    def __init__(self, layout_keys: List[Key], moves_config: Dict[str, Any]):
        self.moves = validate_moves_config(moves_config)

        # Vocabulary: the SET of chars never changes during optimization —
        # only WHICH position each char sits at changes. So the char->index
        # mapping is fixed for the engine's whole lifetime.
        self.chars = [key.char for key in layout_keys if key.char]
        self.char_to_idx = {c: i for i, c in enumerate(self.chars)}
        n = len(self.chars)
        print("n(layout_keys with char):", len(self.chars))
        print("n(unique chars):", len(self.char_to_idx))
        print("dup chars:", [c for c in self.chars if self.chars.count(c) > 1])

        # Per-char geometry arrays. These DO depend on current positions,
        # so they get refreshed by update_layout() — cheaply (O(n) here).
        self.row = np.empty(n, dtype=np.int64)
        self.col = np.empty(n, dtype=np.int64)
        self.home_row = np.empty(n, dtype=np.int64)
        self.home_col = np.empty(n, dtype=np.int64)
        self.hand = np.empty(n, dtype=object)
        self.finger = np.empty(n, dtype=np.int64)
        self.base_cost = np.empty(n, dtype=np.float64)

        col_cfg = self.moves["base_effort"]["column_multiplier"]
        # індекс 0 -> flag=0 (розтяг) -> "col"; індекс 1 -> flag=1 (домашня) -> "home_col"
        self._column_mult_by_flag = np.array(
            [col_cfg["col"], col_cfg["home_col"], col_cfg["other"]], dtype=np.float64
        )
        # Small lookup tables derived from moves_config only (never change).
        finger_mult = self.moves["base_effort"]["finger_multiplier"]
        # index by Finger.value (1..5); index 0 unused.
        self._finger_mult_by_value = np.zeros(6, dtype=np.float64)
        for finger in Finger:
            self._finger_mult_by_value[finger.value] = finger_mult[
                self._get_finger_name(finger.value)
            ]

        # SFS ratio по Finger.value; thumb перескоків не має -> 0
        skip_ratio = self.moves["same_finger"]["skip_row"]["ratio"]
        self._skip_ratio_by_value = np.zeros(6, dtype=np.float64)
        for finger in (Finger.PINKY, Finger.RING, Finger.MIDDLE, Finger.INDEX):
            self._skip_ratio_by_value[finger.value] = skip_ratio[self._get_finger_name(finger.value)]

        # finger alternation
        finger_alt_cfg = self.moves["finger_alternation"]
        self._finger_alt_mult = np.ones((6, 6), dtype=np.float64)
        for a in range (1, 6):
            for b in range(1, 6):
                if a == b:
                    continue
                if a == Finger.THUMB.value or b == Finger.THUMB.value:
                    self._finger_alt_mult[a, b] = finger_alt_cfg["thumb_mult"]
                else:
                    category = _FINGER_PAIR_CATEGORY.get(frozenset({a, b}))
                    if category is None:
                        raise ValueError(f"finger_alternation: no category for pair ({a}, {b}")
                    self._finger_alt_mult[a, b] = finger_alt_cfg[category]

        self.update_layout(layout_keys)

        # Statistics-derived index arrays — expensive to build, so they are
        # cached and only rebuilt when prepare_statistics() is called again.
        self._bigram_idx: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._trigram_idx: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None
        self._skipgram_idx: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None
        self._unigram_idx: Optional[np.ndarray] = None
        self._unigram_weight: Optional[np.ndarray] = None
        # hand runs: n-грами всередині слів -> (index array, weights)
        self._word_ngrams: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None
        self._word_total = 0.0
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

        self._prepare_word_ngrams(statistics.get("words", {}))

        self._statistics_prepared = True
        return self

    def _prepare_word_ngrams(self, words: Dict[str, float]) -> None:
        """Розкладає слова на n-грами, з яких точно відновлюються серії рук
        (див. _evaluate_hand_runs_vectorized). Агрегація по унікальних
        n-грамах замість матриці слів у ~10 разів дешевша на кожен score():
          inner2 — усі пари всередині слова (зміни руки)
          first2 / last2 — перша / остання пара слова (одиночні серії на краю)
          inner3 / inner4 / inner5 — вікна з 3 / 4 / 5 літер
        Слова з символами, яких немає на розкладці, пропускаються.
        """
        counters: Dict[str, Dict[Tuple[int, ...], float]] = {
            name: {} for name in ("inner2", "first2", "last2", "inner3", "inner4", "inner5")
        }

        def add(name, ids, freq):
            bucket = counters[name]
            bucket[ids] = bucket.get(ids, 0.0) + freq

        self._word_total = 0.0
        for word, freq in words.items():
            if len(word) < 2:
                continue
            ids = [self.char_to_idx.get(ch) for ch in word]
            if None in ids:
                continue
            self._word_total += freq
            add("first2", tuple(ids[:2]), freq)
            add("last2", tuple(ids[-2:]), freq)
            for n in (2, 3, 4, 5):
                for i in range(len(ids) - n + 1):
                    add(f"inner{n}", tuple(ids[i:i + n]), freq)

        self._word_ngrams = {}
        for name, bucket in counters.items():
            n = int(name[-1])
            idx = np.array(list(bucket.keys()), dtype=np.int64).reshape(-1, n)
            self._word_ngrams[name] = (idx, np.array(list(bucket.values()), dtype=np.float64))

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
            self.home_row[idx] = key.home_row
            self.col[idx] = key.col
            self.home_col[idx] = key.home_col
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

        if self._word_total > 0:
            self._evaluate_hand_runs_vectorized(metrics)

        metrics.total_penalty = sum((
            metrics.base_effort, metrics.sfb_penalty, metrics.sfs_penalty,
            metrics.double_tap_penalty, metrics.oht_inward_penalty,
            metrics.oht_outward_penalty, metrics.oht_awkward_penalty,
            metrics.hand_run_penalty,
            metrics.skipgram_same_finger_penalty, metrics.skipgram_same_hand_penalty,
            metrics.finger_alternation_penalty, metrics.roll_row_penalty,
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
        # home_col: 0 = дотична колонка, 1 = домашня, інше (напр. 3 у thumb) -> "other"
        column_weight = self._column_mult_by_flag[np.minimum(self.home_col[idx], 2)]
        left_mult = self.moves["hand"]["left_mult"]
        right_mult = self.moves["hand"]["right_mult"]
        hand = self.hand[idx]
        hand_weight = np.where(hand == "left", left_mult, right_mult)
        weight = self._unigram_weight
        row = self.row[idx]
        finger = self.finger[idx]
        base_cost = self.base_cost[idx]

        row_cfg = self.moves["base_effort"]["row_multiplier"]
        row_weight = np.select(
            [row == 0, row == 1, row == 2],
            [row_cfg["top"], row_cfg["home_row"], row_cfg["bottom"]],
            default=row_cfg["other"],
        )
        finger_weight = self._finger_mult_by_value[finger]

        metrics.base_effort += float(np.sum(
            base_cost * row_weight * column_weight * finger_weight * hand_weight * weight
        ))

    def _evaluate_bigrams_vectorized(self, idx1, idx2, weight, metrics):
        hand1, hand2 = self.hand[idx1], self.hand[idx2]
        finger1, finger2 = self.finger[idx1], self.finger[idx2]
        row1, row2 = self.row[idx1], self.row[idx2]
        col1, col2 = self.col[idx1], self.col[idx2]

        same_hand = hand1 == hand2
        same_finger = same_hand & (finger1 == finger2)

        # Чергування рук тут не оцінюється — його баланс рахує
        # _evaluate_hand_runs_vectorized по цілих словах.

        # --- same finger: класифікація руху пальця між двома клавішами ---
        # row: 0 = верхній, 1 = домашній, 2 = нижній (більше = нижче)
        sf_finger = finger1[same_finger]
        sf_row1, sf_row2 = row1[same_finger], row2[same_finger]
        sf_col1, sf_col2 = col1[same_finger], col2[same_finger]
        w_sf = weight[same_finger]
        row_diff = np.abs(sf_row1 - sf_row2)
        same_col = sf_col1 == sf_col2

        sf_cfg = self.moves["same_finger"]
        # Одна клавіша двічі ("нн") — палець не переміщується, це не SFB.
        same_key_mask = (row_diff == 0) & same_col
        # SFB на сусідній ряд або в сусідню колонку. Шкала від легкого до важкого:
        #   lateral (горизонталь, напр. вказівний 4<->5)  <  diagonal_down  <  diagonal_up
        #   vertical — той самий стовпчик, сусідній ряд.
        lateral_mask = (row_diff == 0) & ~same_col
        vertical_mask = (row_diff == 1) & same_col
        diagonal_down_mask = (row_diff == 1) & ~same_col & (sf_row2 > sf_row1)
        diagonal_up_mask = (row_diff == 1) & ~same_col & (sf_row2 < sf_row1)
        sfb_weight = np.select(
            [lateral_mask, vertical_mask, diagonal_down_mask, diagonal_up_mask],
            [sf_cfg["lateral"], sf_cfg["vertical"], sf_cfg["diagonal_down"], sf_cfg["diagonal_up"]],
            default=0.0,
        )
        # для одно-рядних рухів зберігається множник сили пальця
        finger_mult = self._finger_mult_by_value[sf_finger]

        # SFS — перескок через домашній ряд (нижній <-> верхній).
        # Абсолютна шкала, без множника пальця: max — мізинець з дотичної
        # (розтягнутої, home_col == 0) колонки на домашню; решта перескоків =
        # ratio[палець] * max (за замовчуванням 90%).
        skip_mask = row_diff >= 2
        skip_cfg = sf_cfg["skip_row"]
        skip_weight = skip_cfg["max"] * self._skip_ratio_by_value[sf_finger]
        pinky_stretch_to_home = (
            (sf_finger == Finger.PINKY.value)
            & (self.home_col[idx1[same_finger]] == 0)
            & (self.home_col[idx2[same_finger]] == 1)
        )
        skip_weight = np.where(pinky_stretch_to_home, skip_cfg["max"], skip_weight)

        # same hand, different finger — finger_alternation
        same_hand_diff_finger = same_hand & (finger1 != finger2)
        f1 = finger1[same_hand_diff_finger]
        f2 = finger2[same_hand_diff_finger]
        h = hand1[same_hand_diff_finger]
        w = weight[same_hand_diff_finger]

        alt_mult = self._finger_alt_mult[f1, f2]
        hand_mult = np.where(
            h == "left", self.moves["hand"]["left_mult"], self.moves["hand"]["right_mult"]
        )

        metrics.double_tap_penalty += np.sum(
            w_sf[same_key_mask] * finger_mult[same_key_mask] * sf_cfg["same_key"]
        )
        metrics.sfb_penalty += np.sum(w_sf * sfb_weight * finger_mult)
        metrics.sfs_penalty += np.sum(w_sf[skip_mask] * skip_weight[skip_mask])
        metrics.finger_alternation_penalty += np.sum(w * alt_mult * hand_mult)

    def _evaluate_trigrams_vectorized(self, idx1, idx2, idx3, weight, metrics):
        hand1, hand2, hand3 = self.hand[idx1], self.hand[idx2], self.hand[idx3]
        finger1, finger2, finger3 = self.finger[idx1], self.finger[idx2], self.finger[idx3]

        # Пінбол (L-R-L) тепер частина hand_runs (серія довжиною 1).

        # same-hand triples only (усі три на одній руці)
        same_hand_mask = (hand1 == hand2) & (hand2 == hand3)
        f1, f2, f3 = finger1[same_hand_mask], finger2[same_hand_mask], finger3[same_hand_mask]
        w = weight[same_hand_mask]

        inward_mask = (f1 <= f2) & (f2 <= f3) & ((f1 != f2) | (f2 != f3))
        outward_mask = (f1 >= f2) & (f2 >= f3) & ((f1 != f2) | (f2 != f3))
        awkward_mask = ((f1 < f2) & (f2 > f3)) | ((f1 > f2) & (f2 < f3))

        metrics.oht_inward_penalty += np.sum(w[inward_mask] * self.moves["roll"]["inward"])
        metrics.oht_outward_penalty += np.sum(w[outward_mask] * self.moves["roll"]["outward"])
        metrics.oht_awkward_penalty += np.sum(w[awkward_mask] * self.moves["roll"]["awkward"])

        # --- форма перекату по рядах (додається до штрафу напрямку вище) ---
        # Лише справжні перекати: сусідні натискання різними пальцями.
        roll_mask = (f1 != f2) & (f2 != f3)
        r1 = self.row[idx1[same_hand_mask]][roll_mask]
        r2 = self.row[idx2[same_hand_mask]][roll_mask]
        r3 = self.row[idx3[same_hand_mask]][roll_mask]
        rf = np.stack([f1[roll_mask], f2[roll_mask], f3[roll_mask]])
        rr = np.stack([r1, r2, r3])
        rw = w[roll_mask]

        has_top = np.any(rr == 0, axis=0)
        has_bottom = np.any(rr == 2, axis=0)
        # Довгі пальці (середній, безіменний) природно дістають верхній ряд.
        top_by_short_finger = np.any(
            (rr == 0) & ((rf == Finger.INDEX.value) | (rf == Finger.PINKY.value)), axis=0
        )
        # 1) Провал і перескок: проміжна літера скидає палець на нижній ряд,
        #    а наступна змушує стрибнути з нижнього на верхній. Найгірше.
        drop_jump = (r1 != 2) & (r2 == 2) & (r3 == 0)
        # 2) Перекат через ряд: є і верхній, і нижній (напр. третя літера внизу
        #    після верхнього ряду). Трохи гірше.
        row_skip = has_top & has_bottom & ~drop_jump
        # 3) Природна дуга: домашній ряд + верхній лише довгими пальцями
        #    (мізинець home, середній top, вказівний home). Зручно -> бонус.
        natural_arc = has_top & ~has_bottom & ~top_by_short_finger
        # 4) Домашній + нижній без верхнього (дві на home, третя внизу). Нормально.
        bottom_step = has_bottom & ~has_top

        rows_cfg = self.moves["roll_rows"]
        metrics.roll_row_penalty += float(np.sum(rw * np.select(
            [drop_jump, row_skip, natural_arc, bottom_step],
            [rows_cfg["drop_jump"], rows_cfg["row_skip"], rows_cfg["natural_arc"], rows_cfg["bottom_step"]],
            default=0.0,
        )))

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

    def _evaluate_hand_runs_vectorized(self, metrics):
        """Баланс альтернації рук по словах.

        Слово розбивається на серії — підряд натискання однією рукою
        ("берилій" цілком однією рукою = одна серія з 7). Ідеал — серії по
        2-3 (2-2, 3-3, 2-3...): лишають місце для перекатів і не
        перевантажують руку. Штраф за серію:
          1     -> single (пінбол L-R-L), лише всередині слова: одиночна
                   літера на краю слова не є пінболом
          2..3  -> balanced
          4+    -> overload + (довжина - 4) * overload_step

        Без циклу по серіях — через вікна. Серія довжини n містить n-3 вікон
        "4 підряд однією рукою" і n-4 вікон "5 підряд", тому:
          кількість серій 4+   = C4 - C5
          сума (n - 4) по ним  = C5
        Пінбол = вікно з 3, де середня літера іншою рукою, ніж обидві сусідні
        (вони тоді гарантовано існують, тобто серія всередині слова).
        Усього серій = кількість слів + змін руки всередині слів.
        Серії 2-3 = усі - (4+) - пінбол - одиночні на краях слова.
        """
        cfg = self.moves["hand_runs"]
        hand = (self.hand == "right").astype(np.int8)  # 0 = ліва, 1 = права
        ng = self._word_ngrams

        def weight_where(name, predicate):
            idx, w = ng[name]
            if len(idx) == 0:
                return 0.0
            h = hand[idx]
            return float(w[predicate(h)].sum())

        switch = lambda h: h[:, 0] != h[:, 1]
        all_same = lambda h: np.all(h == h[:, :1], axis=1)

        switches = weight_where("inner2", switch)
        edge_single = weight_where("first2", switch) + weight_where("last2", switch)
        single = weight_where("inner3", lambda h: (h[:, 0] != h[:, 1]) & (h[:, 1] != h[:, 2]))
        c4 = weight_where("inner4", all_same)
        c5 = weight_where("inner5", all_same)

        long_runs = c4 - c5
        runs = self._word_total + switches
        short_runs = runs - long_runs - single - edge_single  # серії з 2-3

        metrics.hand_run_penalty += (
            cfg["single"] * single
            + cfg["balanced"] * short_runs
            + cfg["overload"] * long_runs
            + cfg["overload_step"] * c5
        )

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
