"""Тренажер друку: тексти вправ, порядок відкриття літер, перекладач клавіш.

Без Tk — вікно в uiux/trainer.py. Частина 1 (2026-11-24): режим «Слова».

Слова — лише з цитат класики (config/quotes_uk.json), окремого словника нема.
Поки відкритих літер мало і справжніх слів з них майже не складеш, вправа
добирається псевдословами: ланцюжок Маркова за біграмами статистики корпусу,
обмежений відкритими літерами («генератор наборів», як у keybr).

Рівень = скільки літер відкрито: спершу домашній ряд розкладки, далі по
STEP літери за частотою. Нова (остання відкрита) літера — у фокусі: слова з нею
трапляються частіше.

Перекладач: людина друкує на звичайній системній розкладці (ЙЦУКЕН чи QWERTY),
а тренажер дивиться, ЯКА фізична клавіша натиснута, і бере літеру з розкладки
на дошці. Фізична клавіша — з keycode (X11: evdev+8, Windows: VK; обидва не
залежать від вибраної в системі розкладки для літерних клавіш), а якщо keycode
незнайомий (macOS) — із символу за таблицями ЙЦУКЕН/QWERTY. Працює для
геометрій, де в позиціях є `key` (звичайна клавіатура); Corne сама шле літери.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from config.paths import CONFIG_DIR

QUOTES_FILE = CONFIG_DIR / "quotes_uk.json"
ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'"
STEP = 2                 # скільки літер додає кожен рівень
LINE_CHARS = 55          # довжина рядка вправи (приблизно)
FOCUS_WEIGHT = 4.0       # у скільки разів частіше слова з новою літерою
MIN_REAL_WORDS = 12
MIN_ELAPSED_S = 1.0      # раніше швидкість не показуємо (з двох натискань — сміття)      # менше справжніх слів з відкритих літер — домішуємо псевдослова

_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "‘": "'", "`": "'"})


# ----------------------------------------------------------------------
# Тексти
# ----------------------------------------------------------------------
def load_quotes(path: Path | str = QUOTES_FILE) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [q for q in data.get("quotes", []) if q.get("text")]


def normalize(text: str) -> str:
    """Малі літери, апострофи -> ', усе, крім літер і ', -> пробіл."""
    text = text.lower().translate(_APOSTROPHES)
    text = "".join(ch if ch in ALPHABET else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def quote_words(quotes: list[dict]) -> Counter:
    words = Counter()
    for q in quotes:
        for w in normalize(q["text"]).split():
            w = w.strip("'")
            if len(w) >= 2:
                words[w] += 1
    return words


# ----------------------------------------------------------------------
# Рівні: порядок відкриття літер
# ----------------------------------------------------------------------
def unlock_order(chars: dict[int, str], geometry: dict, unigrams: dict) -> list[str]:
    """Літери розкладки в порядку відкриття: домашній ряд (за частотою), потім решта
    (за частотою). chars — {position_id: літера} з дошки."""
    rows = {p["id"]: p["row"] for p in geometry["positions"]}
    letters = {pid: ch for pid, ch in chars.items() if ch in ALPHABET}
    freq = lambda ch: -unigrams.get(ch, 0)
    home = sorted({ch for pid, ch in letters.items() if rows.get(pid) == 1}, key=freq)
    rest = sorted(set(letters.values()) - set(home), key=freq)
    return home + rest


class Order(list):
    """Порядок літер + скільки з них — не домашній ряд (для рівнів)."""
    rest_len: int = 0


def make_order(chars: dict[int, str], geometry: dict, unigrams: dict) -> Order:
    order = Order(unlock_order(chars, geometry, unigrams))
    # символи на AltGr (звичайна клавіатура: ' ї ґ) — в кінець, якщо їх нема на своїх клавішах
    order += [ch for ch in geometry.get("altgr", {}).values() if ch in ALPHABET and ch not in order]
    rows = {p["id"]: p["row"] for p in geometry["positions"]}
    home = {ch for pid, ch in chars.items() if ch in ALPHABET and rows.get(pid) == 1}
    order.rest_len = len(order) - len(home)
    return order


def level_count(order: Order) -> int:
    """Скільки рівнів: 0 — домашній ряд, кожен наступний + STEP літер, останній — усі."""
    return 1 + -(-order.rest_len // STEP)


def letters_at(order: Order, level: int) -> list[str]:
    home = len(order) - order.rest_len
    return list(order[:min(len(order), home + max(0, level) * STEP)])


# ----------------------------------------------------------------------
# Генератор вправ
# ----------------------------------------------------------------------
@dataclass
class WordSource:
    words: Counter
    bigrams: dict                         # статистика корпусу: 'аб' -> к-сть
    rng: random.Random = field(default_factory=random.Random)

    def _real(self, allowed: set[str]) -> list[tuple[str, float]]:
        return [(w, n) for w, n in self.words.items() if set(w) <= allowed]

    def pseudo_word(self, allowed: set[str], focus: str | None = None) -> str:
        """Псевдослово 3–7 літер ланцюжком Маркова за біграмами корпусу."""
        letters = sorted(allowed - {"'"})
        length = self.rng.randint(3, 7)
        word = focus if focus and focus in letters and self.rng.random() < 0.5 else None
        if word is None:
            starts = [self.bigrams.get(" " + ch, 0) + 1 for ch in letters]
            word = self.rng.choices(letters, starts)[0]
        while len(word) < length:
            nxt = [self.bigrams.get(word[-1] + ch, 0) + 1 for ch in letters]
            if word[-1] == word[-2:-1]:      # без потрійних однакових
                nxt = [0 if ch == word[-1] else n for ch, n in zip(letters, nxt)]
            word += self.rng.choices(letters, nxt)[0]
        return word

    def line(self, allowed: list[str] | set[str], focus: str | None = None,
             chars: int = LINE_CHARS) -> str:
        allowed = set(allowed)
        real = self._real(allowed)
        weighted = [(w, n * (FOCUS_WEIGHT if focus and focus in w else 1.0)) for w, n in real]
        out, length, last = [], 0, None
        while length < chars:
            use_real = weighted and (len(weighted) >= MIN_REAL_WORDS or self.rng.random() < 0.3)
            if use_real:
                w = self.rng.choices([w for w, _ in weighted], [n for _, n in weighted])[0]
            else:
                w = self.pseudo_word(allowed, focus)
            if w == last and len(weighted) > 1:
                continue
            out.append(w)
            length += len(w) + 1
            last = w
        return " ".join(out)


# ----------------------------------------------------------------------
# Перекладач фізичних клавіш
# ----------------------------------------------------------------------
_ROWS = {  # XKB-назва -> (X11 keycode, Windows VK, QWERTY, ЙЦУКЕН)
    "TLDE": (49, 0xC0, "`", "'"),
    "BKSL": (51, 0xDC, "\\", "ґ"),
}
for i, (q, y) in enumerate(zip("qwertyuiop[]", "йцукенгшщзхї")):
    vk = ord(q.upper()) if q.isalpha() else {"[": 0xDB, "]": 0xDD}[q]
    _ROWS[f"AD{i + 1:02d}"] = (24 + i, vk, q, y)
for i, (q, y) in enumerate(zip("asdfghjkl;'", "фівапролджє")):
    vk = ord(q.upper()) if q.isalpha() else {";": 0xBA, "'": 0xDE}[q]
    _ROWS[f"AC{i + 1:02d}"] = (38 + i, vk, q, y)
for i, (q, y) in enumerate(zip("zxcvbnm,./", "ячсмитьбю.")):
    vk = ord(q.upper()) if q.isalpha() else {",": 0xBC, ".": 0xBE, "/": 0xBF}[q]
    _ROWS[f"AB{i + 1:02d}"] = (52 + i, vk, q, y)

X11_KEYCODES = {v[0]: k for k, v in _ROWS.items()}
WIN_VK = {v[1]: k for k, v in _ROWS.items()}
BY_CHAR = {**{v[2]: k for k, v in _ROWS.items()}, **{v[3]: k for k, v in _ROWS.items()}}
BY_CHAR.update({ch.upper(): k for ch, k in list(BY_CHAR.items()) if ch.isalpha()})

# біти event.state, що означають AltGr / Alt (Tk): X11 — Mod1 (Alt) і Mod5 (ISO_Level3);
# Windows — Alt (0x20000; AltGr приходить як Ctrl+Alt)
ALTGR_MASK = {"x11": 0x08 | 0x80, "win32": 0x20000}
SPACE_KEYCODE = {"x11": 65, "win32": 0x20}


def can_translate(geometry: dict) -> bool:
    return any(p.get("key") for p in geometry["positions"])


@dataclass
class Translator:
    chars: dict[int, str]            # {position_id: літера} з дошки
    geometry: dict
    windowing: str = "x11"           # root.tk.call("tk", "windowingsystem"): x11 / win32 / aqua

    def __post_init__(self):
        self.by_key = {p["key"]: self.chars.get(p["id"], "") for p in self.geometry["positions"]
                       if p.get("key")}
        self.altgr = self.geometry.get("altgr", {})

    def physical_key(self, keycode: int, char: str) -> str | None:
        table = X11_KEYCODES if self.windowing == "x11" else WIN_VK if self.windowing == "win32" else {}
        return table.get(keycode) or BY_CHAR.get(char)

    def translate(self, keycode: int, char: str, state: int) -> str | None:
        """Літера нової розкладки для натискання або None (не літерна клавіша)."""
        if char == " " or keycode == SPACE_KEYCODE.get(self.windowing):
            return " "
        key = self.physical_key(keycode, char)
        if key is None:
            return None
        ch = self.by_key.get(key, "")
        if ch and state & ALTGR_MASK.get(self.windowing, 0):
            ch = self.altgr.get(ch, ch)
        return ch or None


def as_is(char: str) -> str | None:
    """Без перекладу: літера, яку дала система (нормалізовані апострофи, малі)."""
    if not char:
        return None
    ch = char.lower().translate(_APOSTROPHES)
    return ch if ch in ALPHABET or ch == " " else None


# ----------------------------------------------------------------------
# Сесія: поточний рядок, помилки, швидкість
# ----------------------------------------------------------------------
@dataclass
class Session:
    text: str
    pos: int = 0
    errors: int = 0
    wrong_at: set = field(default_factory=set)     # позиції з помилкою (червоні)
    misses: Counter = field(default_factory=Counter)  # літера -> скільки разів не та
    started: float | None = None
    finished: float | None = None

    @property
    def done(self) -> bool:
        return self.pos >= len(self.text)

    def type(self, ch: str, now: float) -> bool:
        """Натиснута літера ch. True — правильна (курсор далі). Неправильна —
        курсор стоїть, позиція позначається помилкою (як у keybr)."""
        if self.done:
            return False
        if self.started is None:
            self.started = now
        if ch == self.text[self.pos]:
            self.pos += 1
            if self.done:
                self.finished = now
            return True
        self.errors += 1
        self.wrong_at.add(self.pos)
        self.misses[self.text[self.pos]] += 1
        return False

    def cpm(self, now: float) -> float:
        """Знаків за хвилину (правильно набраних)."""
        if self.started is None or self.pos < 2:
            return 0.0
        elapsed = (self.finished or now) - self.started
        return 60.0 * (self.pos - 1) / elapsed if elapsed >= MIN_ELAPSED_S else 0.0

    def accuracy(self) -> float:
        total = self.pos + self.errors
        return 100.0 * self.pos / total if total else 100.0
