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

Для SA — delta-оцінка: ``load(keys)`` рахує розкладку повністю і кешує
внесок кожної n-грами; ``try_layout(keys)`` перераховує лише n-грами з
переміщеними літерами; ``accept()`` робить кандидата новою базою. Внески
бі/три/скіп-грам беруться з таблиць за кортежами позицій, побудованих у
``__init__`` з ``moves`` — тому ``moves`` після створення engine не міняти.

``score_from_statistics(statistics)`` and ``calculate_total_penalty(...)`` are
kept as slow, self-contained convenience wrappers for one-off scoring (tests,
scripts) — they rebuild everything from scratch every call, same as before.
Do NOT use them inside a hot loop.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple
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
        "lateral_pinky": None,
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
    "finger_load": {
        "cap": ("pinky", "ring", "middle", "index"),
        "over_cap": None,
    },
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
def load_moves_config(path: str | Path) -> Dict[str, Any]:
    """Load and validate the numeric movement-policy YAML file."""
    with Path(path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    return validate_moves_config(config)


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

def _validate_numeric_values(values: Dict[str, Any], names: Tuple[str, ...], path: str) -> None:
    for name in names:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"moves config value '{path}.{name}' must be numeric")

def calculate_total_penalty(
    layout: Layout,
    statistics: Dict[str, Any],
    moves_config: Optional[Dict[str, Any]] = None,
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
    return engine.score().total_penalty / 1000000000


class _Family(NamedTuple):
    """Сімейство n-грам з однаковим правилом оцінки."""
    keys: np.ndarray           # (k, N) char-індекси (транспоновано) або (N,) маски літер
    weight: np.ndarray         # (N,) частоти
    code: Callable             # keys -> код (позицій або рук) для таблиць
    tables: Dict[str, np.ndarray]  # поле ScoreMetrics -> штраф за одиницю частоти
    total: np.ndarray          # сума tables
    masks: np.ndarray          # (N,) uint64: біт c — літера c є в n-грамі
    by_hand: bool              # залежить лише від рук літер (hand_runs)


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

        # Геометрія фізичних позицій (не змінюється). Позиції нумеруються
        # щільно 0..P-1 у порядку layout_keys.
        self._pos_index = {key.position_id: i for i, key in enumerate(layout_keys)}
        self._pos = SimpleNamespace(
            row=np.array([key.row for key in layout_keys], dtype=np.int64),
            home_row=np.array([key.home_row for key in layout_keys], dtype=np.int64),
            col=np.array([key.col for key in layout_keys], dtype=np.int64),
            home_col=np.array([key.home_col for key in layout_keys], dtype=np.int64),
            hand=np.array([key.hand.value == "right" for key in layout_keys], dtype=np.int8),  # 0 = ліва, 1 = права
            finger=np.array([key.finger.value for key in layout_keys], dtype=np.int64),
            base_cost=np.array([key.base_cost for key in layout_keys], dtype=np.float64),
        )

        # Per-char geometry arrays. These DO depend on current positions,
        # so they get refreshed by update_layout() — cheaply (O(n) here).
        self.position = np.empty(n, dtype=np.int64)  # щільний індекс позиції
        self.row = np.empty(n, dtype=np.int64)
        self.col = np.empty(n, dtype=np.int64)
        self.home_row = np.empty(n, dtype=np.int64)
        self.home_col = np.empty(n, dtype=np.int64)
        self.hand = np.empty(n, dtype=np.int8)  # 0 = ліва, 1 = права
        self.finger = np.empty(n, dtype=np.int64)
        self.base_cost = np.empty(n, dtype=np.float64)
        # біт літери для масок n-грам (hand_runs); 36 літер вміщаються в 64 біти
        if n > 64:
            raise ValueError("hand_runs masks support at most 64 chars")
        self._char_bits = np.left_shift(np.uint64(1), np.arange(n, dtype=np.uint64))

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

        # Ліміт навантаження пальця (частка всіх натискань) по Finger.value;
        # thumb не обмежується -> 1.0
        load_cap = self.moves["finger_load"]["cap"]
        self._load_cap_by_value = np.ones(6, dtype=np.float64)
        for finger in (Finger.PINKY, Finger.RING, Finger.MIDDLE, Finger.INDEX):
            self._load_cap_by_value[finger.value] = load_cap[self._get_finger_name(finger.value)]

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

        # Внесок бі/три/скіп-грами залежить лише від позицій її літер, тому
        # штраф за одиницю частоти рахується наперед для кожного кортежу
        # позицій (P^2 / P^3) — тими самими *_terms, що описують модель.
        # Оцінка далі = таблиця[код позицій] * частота.
        self._pos_effort = self._position_effort(self._pos)
        self._pos_slot = self._pos.hand.astype(np.int64) * 6 + self._pos.finger  # палець з рукою, 0..11
        self._load_cap = np.zeros(12)
        self._position_tables = {
            "bigrams": self._build_position_tables(self._bigram_terms, 2),
            "trigrams": self._build_position_tables(self._trigram_terms, 3),
            "skipgrams": self._build_position_tables(self._skipgram_terms, 2),
        }

        self.update_layout(layout_keys)

        # Statistics-derived index arrays — expensive to build, so they are
        # cached and only rebuilt when prepare_statistics() is called again.
        self._families: Dict[str, _Family] = {}
        self._unigram_idx: Optional[np.ndarray] = None
        self._unigram_weight: Optional[np.ndarray] = None
        self._word_total = 0.0
        self._hand_run_const = 0.0
        self._statistics_prepared = False

        # Delta-стан (load / try_layout / accept): внесок кожної n-грами для
        # завантаженої розкладки; при мутації перераховуються лише n-грами
        # з переміщеними літерами.
        self._cost: Dict[str, np.ndarray] = {}
        self._loaded_position: Optional[np.ndarray] = None
        self._loaded_hand: Optional[np.ndarray] = None
        self._ngram_total = 0.0
        self._pending = None

    def _build_position_tables(self, terms, k: int) -> Dict[str, np.ndarray]:
        """{поле ScoreMetrics: штраф за одиницю частоти} для всіх P^k
        кортежів позицій; індекс — код позицій (див. _position_code)."""
        p = len(self._pos.row)
        idx = np.indices((p,) * k).reshape(k, -1)
        return terms(self._pos, idx, np.ones(idx.shape[1]))

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
        self._families = {}
        for name, n in (("bigrams", 2), ("trigrams", 3), ("skipgrams", 2)):
            idx, weight = self._prepare_ngram_arrays(statistics.get(name, {}), n)
            self._add_family(name, idx, self._char_masks(idx), weight, self._position_code,
                             self._position_tables[name], by_hand=False)

        uni_idx, uni_w = [], []
        for char, freq in statistics.get("unigrams", {}).items():
            i = self.char_to_idx.get(char)
            if i is None:
                continue
            uni_idx.append(i)
            uni_w.append(freq)
        self._unigram_idx = np.array(uni_idx, dtype=np.int64)
        self._unigram_weight = np.array(uni_w, dtype=np.float64)
        self._load_cap = np.tile(self._load_cap_by_value, 2) * self._unigram_weight.sum()

        self._prepare_word_ngrams(statistics.get("words", {}))

        self._loaded_position = None
        self._statistics_prepared = True
        return self

    def _add_family(self, name, keys, masks, weight, code, tables, by_hand) -> None:
        if len(weight) == 0:
            return
        self._families[name] = _Family(
            keys, weight, code, tables, sum(tables.values()), masks, by_hand,
        )

    def _char_masks(self, idx: np.ndarray) -> np.ndarray:
        return np.bitwise_or.reduce(self._char_bits[idx], axis=0)

    def _prepare_word_ngrams(self, words: Dict[str, float]) -> None:
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

        Підставивши все, штраф лінійний за частотами n-грам:
          константа (_hand_run_constant)
          + сума по n-грамах w * coef, якщо n-грама спрацьовує (одна рука /
            зміна руки / пінбол).
        Тому слова розкладаються на агреговані унікальні n-грами (у ~10
        разів дешевше за матрицю слів):
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

        cfg = self.moves["hand_runs"]
        balanced = cfg["balanced"]
        # Пари і вікна 4-5 залежать лише від того, чи всі літери на одній руці
        # (same). Зміна руки в парі = 1 - same, тож balanced * w * switch =
        # balanced * w - balanced * w * same: перша частина — константа, друга
        # разом з вікнами 4-5 — одне сімейство "набір літер -> вага" (same).
        same_coef = {
            "inner2": -balanced,                                         # +серія на кожну зміну руки
            "first2": balanced,                                          # одиночна на краю слова
            "last2": balanced,
            "inner4": cfg["overload"] - balanced,                        # C4
            "inner5": balanced - cfg["overload"] + cfg["overload_step"], # C5
        }
        self._hand_run_const = balanced * self._word_total
        by_set: Dict[int, float] = {}
        for name, coef in same_coef.items():
            for ids, freq in counters[name].items():
                if name in ("inner2", "first2", "last2"):
                    self._hand_run_const -= coef * freq
                mask = 0
                for c in ids:
                    mask |= 1 << c
                by_set[mask] = by_set.get(mask, 0.0) + coef * freq
        masks = np.array(list(by_set.keys()), dtype=np.uint64)
        self._add_family(
            "words_same_hand", masks, masks, np.array(list(by_set.values()), dtype=np.float64),
            self._same_hand_code, {"hand_run_penalty": np.array([0.0, 1.0])}, by_hand=True,
        )

        # Пінбол залежить від порядку рук (010 / 101) — бітовий код рук.
        bucket = counters["inner3"]
        idx = np.ascontiguousarray(np.array(list(bucket.keys()), dtype=np.int64).reshape(-1, 3).T)
        pinball = np.zeros(8)
        pinball[[0b010, 0b101]] = cfg["single"] - balanced
        self._add_family(
            "words_pinball", idx, self._char_masks(idx),
            np.array(list(bucket.values()), dtype=np.float64),
            self._hand_code, {"hand_run_penalty": pinball}, by_hand=True,
        )

    def _prepare_ngram_arrays(self, ngrams: Dict[str, float], n: int):
        """-> (idx (n, N) char-індекси, weight (N,)). idx транспоновано: кожна
        позиція n-грами — суцільний масив, щоб коди збиралися поелементно."""
        rows, w = [], []
        for ngram, freq in ngrams.items():
            if len(ngram) != n:
                continue
            ids = [self.char_to_idx.get(ch) for ch in ngram]
            if None in ids:
                continue
            rows.append(ids)
            w.append(freq)
        idx = np.array(rows, dtype=np.int64).reshape(-1, n)
        return np.ascontiguousarray(idx.T), np.array(w, dtype=np.float64)

    # -----------------------------------------------------------
    # Cheap, per-mutation update
    # -----------------------------------------------------------

    def update_layout(self, layout_keys: List[Key]) -> "MovementScoringEngine":
        """Refresh per-char geometry after a mutation. O(number of chars).

        IMPORTANT: the set of chars in ``layout_keys`` must be exactly the
        vocabulary this engine was built with — mutations may move chars
        between positions, but must not introduce or remove chars.
        """
        char_to_idx = self.char_to_idx
        pos_index = self._pos_index
        for key in layout_keys:
            if key.char:
                self.position[char_to_idx[key.char]] = pos_index[key.position_id]
        pos = self._pos
        self.row = pos.row[self.position]
        self.home_row = pos.home_row[self.position]
        self.col = pos.col[self.position]
        self.home_col = pos.home_col[self.position]
        self.hand = pos.hand[self.position]
        self.finger = pos.finger[self.position]
        self.base_cost = pos.base_cost[self.position]
        self._hand64 = self.hand.astype(np.int64)
        self._right_mask = np.bitwise_or.reduce(self._char_bits[self.hand == 1])
        return self

    def _position_code(self, idx: np.ndarray) -> np.ndarray:
        """Код кортежу позицій n-грами: p1*P^(k-1) + ... + pk."""
        p = len(self._pos.row)
        code = self.position[idx[0]]
        for j in range(1, idx.shape[0]):
            code = code * p + self.position[idx[j]]
        return code

    def _same_hand_code(self, masks: np.ndarray) -> np.ndarray:
        """1, якщо всі літери n-грами (маска по char-індексах) на одній руці."""
        right = self._right_mask
        return (((masks & right) == 0) | ((masks & ~right) == 0)).astype(np.int64)

    def _hand_code(self, idx: np.ndarray) -> np.ndarray:
        """Бітовий код рук n-грами: біт j = рука j-ї літери."""
        hand = self._hand64
        code = hand[idx[0]]
        for j in range(1, idx.shape[0]):
            code = code | (hand[idx[j]] << j)
        return code

    # -----------------------------------------------------------
    # Scoring — pure NumPy, no Python-level loop over the corpus
    # -----------------------------------------------------------

    def _require_statistics(self) -> None:
        if not self._statistics_prepared:
            raise RuntimeError(
                "prepare_statistics() must be called at least once before score()"
            )

    def score(self) -> ScoreMetrics:
        """Fast path: score the layout currently loaded via update_layout(),
        against the statistics currently cached via prepare_statistics().
        Повна розбивка по компонентах; для SA-циклу — load/try_layout.
        """
        self._require_statistics()
        metrics = ScoreMetrics()
        metrics.base_effort, metrics.finger_load_penalty = self._unigram_terms()
        metrics.hand_run_penalty = self._hand_run_constant()
        for fam in self._families.values():
            code = fam.code(fam.keys)
            for field, table in fam.tables.items():
                # не np.dot: багатопотоковий BLAS під cpulimit у рази повільніший
                setattr(metrics, field, getattr(metrics, field) + float((table[code] * fam.weight).sum()))

        metrics.total_penalty = sum((
            metrics.base_effort, metrics.sfb_penalty, metrics.sfs_penalty,
            metrics.double_tap_penalty, metrics.oht_inward_penalty,
            metrics.oht_outward_penalty, metrics.oht_awkward_penalty,
            metrics.hand_run_penalty, metrics.finger_load_penalty,
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

    # -----------------------------------------------------------
    # Delta-оцінка для SA: load -> (try_layout -> accept?)*
    # -----------------------------------------------------------

    def load(self, layout_keys: List[Key]) -> float:
        """Повністю оцінює розкладку і запам'ятовує внесок кожної n-грами —
        база для try_layout. Повертає total_penalty."""
        self._require_statistics()
        self.update_layout(layout_keys)
        self._cost = {
            name: fam.total[fam.code(fam.keys)] * fam.weight
            for name, fam in self._families.items()
        }
        self._loaded_position = self.position.copy()
        self._loaded_hand = self.hand.copy()
        self._ngram_total = sum(float(c.sum()) for c in self._cost.values())
        self._pending = None
        return sum(self._unigram_terms()) + self._hand_run_constant() + self._ngram_total

    def try_layout(self, layout_keys: List[Key]) -> float:
        """total_penalty кандидата, рахуючи заново лише n-грами з літерами,
        що змінили позицію (для hand_runs — руку) відносно load()/accept().
        Кеш не змінюється, поки не викликано accept(). Після try_layout
        геометрія (row, hand, ...) відповідає кандидату."""
        if self._loaded_position is None:
            raise RuntimeError("load() must be called before try_layout()")
        self.update_layout(layout_keys)
        moved = self.position != self._loaded_position
        moved_bits = np.bitwise_or.reduce(self._char_bits[moved])
        moved_hand_bits = np.bitwise_or.reduce(self._char_bits[moved & (self.hand != self._loaded_hand)])
        ngram_total = self._ngram_total
        changes = []
        for name, fam in self._families.items():
            bits = moved_hand_bits if fam.by_hand else moved_bits
            if bits == 0:
                continue
            sub = np.flatnonzero((fam.masks & bits) != 0)
            new = fam.total[fam.code(fam.keys[..., sub])] * fam.weight[sub]
            ngram_total += float(new.sum()) - float(self._cost[name][sub].sum())
            changes.append((name, sub, new))
        self._pending = (self.position.copy(), self.hand.copy(), changes, ngram_total)
        return sum(self._unigram_terms()) + self._hand_run_constant() + ngram_total

    def accept(self) -> None:
        """Робить останній try_layout базою для наступних."""
        if self._pending is None:
            raise RuntimeError("accept() without a preceding try_layout()")
        position, hand, changes, ngram_total = self._pending
        for name, sub, new in changes:
            self._cost[name][sub] = new
        self._loaded_position = position
        self._loaded_hand = hand
        self._ngram_total = ngram_total
        self._pending = None

    def _hand_run_constant(self) -> float:
        # частина hand_runs, що не залежить від розкладки (див. _prepare_word_ngrams)
        return self._hand_run_const

    def _unigram_terms(self) -> Tuple[float, float]:
        """(base_effort, finger_load_penalty) — по ~36 літерах, дешевше
        рахувати завжди повністю, ніж інкрементально."""
        idx = self._unigram_idx
        if idx is None or len(idx) == 0:
            return 0.0, 0.0
        pos = self.position[idx]
        weight = self._unigram_weight
        base_effort = float((self._pos_effort[pos] * weight).sum())

        # Навантаження пальців: натискання понад ліміт (cap — частка від усіх)
        # штрафуються по over_cap кожне. Розподіляє роботу між пальцями, щоб
        # часті літери не збиралися на одному (напр. "а" на мізинці).
        load = np.bincount(self._pos_slot[pos], weights=weight, minlength=12)
        finger_load = float(
            self.moves["finger_load"]["over_cap"] * np.maximum(load - self._load_cap, 0.0).sum()
        )
        return base_effort, finger_load

    def _position_effort(self, g) -> np.ndarray:
        """base_effort за одиницю частоти для кожної позиції."""
        # home_col: 0 = дотична колонка, 1 = домашня, інше (напр. 3 у thumb) -> "other"
        column_weight = self._column_mult_by_flag[np.minimum(g.home_col, 2)]
        hand_weight = np.where(g.hand == 0, self.moves["hand"]["left_mult"], self.moves["hand"]["right_mult"])
        row_cfg = self.moves["base_effort"]["row_multiplier"]
        row_weight = np.select(
            [g.row == 0, g.row == 1, g.row == 2],
            [row_cfg["top"], row_cfg["home_row"], row_cfg["bottom"]],
            default=row_cfg["other"],
        )
        finger_weight = self._finger_mult_by_value[g.finger]
        return g.base_cost * row_weight * column_weight * finger_weight * hand_weight

    def _bigram_terms(self, g, idx, weight):
        idx1, idx2 = idx
        hand1, hand2 = g.hand[idx1], g.hand[idx2]
        finger1, finger2 = g.finger[idx1], g.finger[idx2]
        row1, row2 = g.row[idx1], g.row[idx2]
        col1, col2 = g.col[idx1], g.col[idx2]

        same_hand = hand1 == hand2
        same_finger = same_hand & (finger1 == finger2)

        # Чергування рук тут не оцінюється — його баланс рахує
        # _prepare_word_ngrams по цілих словах.

        # --- same finger: класифікація руху пальця між двома клавішами ---
        # row: 0 = верхній, 1 = домашній, 2 = нижній (більше = нижче)
        row_diff = np.abs(row1 - row2)
        same_col = col1 == col2

        sf_cfg = self.moves["same_finger"]
        # Одна клавіша двічі ("нн") — палець не переміщується, це не SFB.
        same_key_mask = same_finger & (row_diff == 0) & same_col
        # SFB на сусідній ряд або в сусідню колонку. Шкала від легкого до важкого:
        #   lateral (горизонталь, напр. вказівний 4<->5)  <  diagonal_down  <  diagonal_up
        #   vertical — той самий стовпчик, сусідній ряд.
        #   lateral_pinky — горизонталь мізинцем (у дотичну колонку): розтяг,
        #   а не легкий зсув, як у вказівного.
        lateral_mask = same_finger & (row_diff == 0) & ~same_col
        lateral_pinky_mask = lateral_mask & (finger1 == Finger.PINKY.value)
        lateral_mask = lateral_mask & ~lateral_pinky_mask
        vertical_mask = same_finger & (row_diff == 1) & same_col
        diagonal_down_mask = same_finger & (row_diff == 1) & ~same_col & (row2 > row1)
        diagonal_up_mask = same_finger & (row_diff == 1) & ~same_col & (row2 < row1)
        sfb_weight = np.select(
            [lateral_mask, lateral_pinky_mask, vertical_mask, diagonal_down_mask, diagonal_up_mask],
            [sf_cfg["lateral"], sf_cfg["lateral_pinky"], sf_cfg["vertical"],
             sf_cfg["diagonal_down"], sf_cfg["diagonal_up"]],
            default=0.0,
        )
        # для одно-рядних рухів зберігається множник сили пальця
        finger_mult = self._finger_mult_by_value[finger1]

        # SFS — перескок через домашній ряд (нижній <-> верхній).
        # Абсолютна шкала, без множника пальця: max — мізинець з дотичної
        # (розтягнутої, home_col == 0) колонки на домашню; решта перескоків =
        # ratio[палець] * max (за замовчуванням 90%).
        skip_mask = same_finger & (row_diff >= 2)
        skip_cfg = sf_cfg["skip_row"]
        skip_weight = skip_cfg["max"] * self._skip_ratio_by_value[finger1]
        pinky_stretch_to_home = (
            (finger1 == Finger.PINKY.value)
            & (g.home_col[idx1] == 0)
            & (g.home_col[idx2] == 1)
        )
        skip_weight = np.where(pinky_stretch_to_home, skip_cfg["max"], skip_weight)

        # same hand, different finger — finger_alternation
        alt_mask = same_hand & (finger1 != finger2)
        hand_mult = np.where(
            hand1 == 0, self.moves["hand"]["left_mult"], self.moves["hand"]["right_mult"]
        )

        return {
            "double_tap_penalty": np.where(same_key_mask, weight * finger_mult * sf_cfg["same_key"], 0.0),
            "sfb_penalty": weight * sfb_weight * finger_mult,
            "sfs_penalty": np.where(skip_mask, weight * skip_weight, 0.0),
            "finger_alternation_penalty": np.where(
                alt_mask, weight * self._finger_alt_mult[finger1, finger2] * hand_mult, 0.0
            ),
        }

    def _trigram_terms(self, g, idx, weight):
        idx1, idx2, idx3 = idx
        hand1, hand2, hand3 = g.hand[idx1], g.hand[idx2], g.hand[idx3]
        f1, f2, f3 = g.finger[idx1], g.finger[idx2], g.finger[idx3]

        # Пінбол (L-R-L) тепер частина hand_runs (серія довжиною 1).

        # same-hand triples only (усі три на одній руці)
        same_hand_mask = (hand1 == hand2) & (hand2 == hand3)

        inward_mask = same_hand_mask & (f1 <= f2) & (f2 <= f3) & ((f1 != f2) | (f2 != f3))
        outward_mask = same_hand_mask & (f1 >= f2) & (f2 >= f3) & ((f1 != f2) | (f2 != f3))
        awkward_mask = same_hand_mask & (((f1 < f2) & (f2 > f3)) | ((f1 > f2) & (f2 < f3)))

        roll_cfg = self.moves["roll"]
        terms = {
            "oht_inward_penalty": np.where(inward_mask, weight * roll_cfg["inward"], 0.0),
            "oht_outward_penalty": np.where(outward_mask, weight * roll_cfg["outward"], 0.0),
            "oht_awkward_penalty": np.where(awkward_mask, weight * roll_cfg["awkward"], 0.0),
        }

        # --- форма перекату по рядах (додається до штрафу напрямку вище) ---
        # Лише справжні перекати: сусідні натискання різними пальцями.
        roll_mask = same_hand_mask & (f1 != f2) & (f2 != f3)
        r1, r2, r3 = g.row[idx1], g.row[idx2], g.row[idx3]

        has_top = (r1 == 0) | (r2 == 0) | (r3 == 0)
        has_bottom = (r1 == 2) | (r2 == 2) | (r3 == 2)
        # Довгі пальці (середній, безіменний) природно дістають верхній ряд.
        short1 = (f1 == Finger.INDEX.value) | (f1 == Finger.PINKY.value)
        short2 = (f2 == Finger.INDEX.value) | (f2 == Finger.PINKY.value)
        short3 = (f3 == Finger.INDEX.value) | (f3 == Finger.PINKY.value)
        top_by_short_finger = ((r1 == 0) & short1) | ((r2 == 0) & short2) | ((r3 == 0) & short3)
        # 1) Провал і перескок: проміжна літера скидає палець на нижній ряд,
        #    а наступна змушує стрибнути з нижнього на верхній. Найгірше.
        drop_jump = roll_mask & (r1 != 2) & (r2 == 2) & (r3 == 0)
        # 2) Перекат через ряд: є і верхній, і нижній (напр. третя літера внизу
        #    після верхнього ряду). Трохи гірше.
        row_skip = roll_mask & has_top & has_bottom & ~drop_jump
        # 3) Природна дуга: домашній ряд + верхній лише довгими пальцями
        #    (мізинець home, середній top, вказівний home). Зручно -> бонус.
        natural_arc = roll_mask & has_top & ~has_bottom & ~top_by_short_finger
        # 4) Домашній + нижній без верхнього (дві на home, третя внизу). Нормально.
        bottom_step = roll_mask & has_bottom & ~has_top

        rows_cfg = self.moves["roll_rows"]
        terms["roll_row_penalty"] = weight * np.select(
            [drop_jump, row_skip, natural_arc, bottom_step],
            [rows_cfg["drop_jump"], rows_cfg["row_skip"], rows_cfg["natural_arc"], rows_cfg["bottom_step"]],
            default=0.0,
        )
        return terms

    def _skipgram_terms(self, g, idx, weight):
        idx1, idx2 = idx
        same_hand = g.hand[idx1] == g.hand[idx2]
        same_finger = same_hand & (g.finger[idx1] == g.finger[idx2])
        skip_cfg = self.moves.get("skip_bigram", {})
        return {
            "skipgram_same_finger_penalty": np.where(
                same_finger, weight * skip_cfg.get("same_finger", 1.0), 0.0
            ),
            "skipgram_same_hand_penalty": np.where(
                same_hand & ~same_finger, weight * skip_cfg.get("same_hand", 0.1), 0.0
            ),
        }

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
