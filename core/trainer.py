"""Тренажер друку: тексти вправ, порядок відкриття літер, перекладач клавіш.

Без Tk — вікно в uiux/trainer.py. Частина 1 (2026-11-24): режим «Слова».
Частина 2 (2026-11-25): режим «Поєднання» (найдорожчі для розкладки біграми й
триграми — MovementScoringEngine.ngram_penalty), статистика по літерах між
сесіями (trainer_stats.json у теці налаштувань), «Сам підвищуй» (should_level_up);
слова зі слабкими літерами — частіше. Частина 3: «Класика» — цитата цілком (pick_quote),
малими літерами без розділових, як і решта вправ (або з великими / розділовими — два
перемикачі); автор і твір — у підказці. Перекладач знає Shift і цифровий ряд — таблиця
клавіш та сама, що й в експорті (core/export.keymap). «Свій текст…» — .txt людини, уривками
по черзі (read_text_file, text_chunks), з тими самими перемикачами, що й «Класика».

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

from config.paths import CONFIG_DIR, user_data_dir

QUOTES_FILE = CONFIG_DIR / "quotes_uk.json"
ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'"
STEP = 2                 # скільки літер додає кожен рівень
LINE_CHARS = 55          # довжина рядка вправи (приблизно)
FOCUS_WEIGHT = 4.0       # у скільки разів частіше слова з новою літерою
WEAK_WEIGHT = 2.0        # ... і зі слабкою (статистика по літерах)
WEAK_TOP = 3             # скільки найслабших літер підсилювати
MIN_REAL_WORDS = 12
MIN_ELAPSED_S = 1.0      # раніше швидкість не показуємо (з двох натискань — сміття)
PAUSE_S = 3.0            # довша пауза між натисканнями — не рахуємо в час літери
HARD_TOP = 12            # скільки найважчих поєднань тренує «Поєднання»
REPEAT = (2, 3)          # скільки слів поспіль на одне поєднання
STATS_FILE = "trainer_stats.json"
MIN_SAMPLES = 15         # менше натискань літери — в «слабкі» не беремо
LEVEL_UP_LINES = 3       # «Сам підвищуй»: стільки останніх рядків рівня
LEVEL_UP_ACCURACY = 95.0  # ... кожен з точністю не нижче, %
LEVEL_UP_SPREAD = 0.2    # ... і швидкість стабільна: (макс - мін) / середнє

_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "‘": "'", "`": "'"})
PUNCT = ',.!?:;-"()'      # розділові, що бувають у «Класиці» з перемикачем «Розділові»
# розділові, що відкриваються рівнями, як літери (стоять на власних клавішах розкладки):
# у «Словах» вони йдуть після слів, у «Класиці» з «Розділовими» — підсвічені на схемі
WORD_PUNCT = ",."
PUNCT_AFTER = {",": 0.10, ".": 0.07}   # імовірність знака після слова (частота в корпусі ~1:9 і ~1:11 слів)
PUNCT_FOCUS = 0.30                     # ... якщо це нова (у фокусі) чи слабка клавіша
_PUNCT_MAP = str.maketrans({"—": "-", "–": "-", "‑": "-", "„": '"', "“": '"', "”": '"', "«": '"',
                            "»": '"', "…": "..."})
SHIFT_MASK = 0x01         # біт Shift у event.state (X11 і Windows)


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


def quote_text(quote: dict, caps: bool = False, punct: bool = False) -> str:
    """Цитата для «Класики»: апостроф лишається лише між літерами; caps — великі літери
    як в оригіналі, punct — розділові (тире -> -, лапки -> ", … -> ...), інакше прибрано."""
    if not caps and not punct:
        text = normalize(quote["text"])
    else:
        text = quote["text"].translate(_APOSTROPHES).translate(_PUNCT_MAP)
        keep = set(ALPHABET) | set(ALPHABET.upper()) | (set(PUNCT) if punct else set())
        text = "".join(ch if ch in keep else " " for ch in text)
        if not caps:
            text = text.lower()
        if punct:
            # від викинутих слів (латиниця, цифри) лишаються сироти: «було! .» -> «було!»
            text = re.sub(r"([,.!?:;])(?:\s+[,.!?:;]+)+", r"\1", text)
            text = re.sub(r"(^|\s)-(?=\s*(-|$))", r"\1", text)
            text = re.sub(r"\s+([,.!?:;)])", r"\1", text)      # без пробілу перед , . ! ? : ; )
            text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"(?<![^\W\d_])'|'(?![^\W\d_])", "", text)
    return re.sub(r"\s+", " ", text).strip()


OWN_CHARS = 110             # довжина уривку «Свого тексту» (приблизно, по межі слова)
OWN_MAX_BYTES = 2_000_000   # з більшого файлу береться початок


def read_text_file(path: Path | str) -> str:
    """Текст .txt: UTF-8 (з BOM чи без), інакше cp1251 (старі Windows-файли)."""
    with open(path, "rb") as f:
        raw = f.read(OWN_MAX_BYTES)
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def text_chunks(text: str, caps: bool = False, punct: bool = False, size: int = OWN_CHARS) -> list[str]:
    """Свій текст -> уривки ~size знаків по межі слова (і речення, якщо близько):
    та сама чистка, що й у «Класиці» (quote_text)."""
    clean = quote_text({"text": text}, caps, punct)
    words, out, cur = clean.split(" "), [], ""
    for w in words:
        if not w:
            continue
        if cur and len(cur) + 1 + len(w) > size:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
        if punct and len(cur) >= size * 0.7 and cur[-1] in ".!?":
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def same_place(old: list[str], idx: int, new: list[str]) -> int:
    """Номер уривка в new, де той самий початок тексту, що й old[idx] (рахуємо літери:
    «Великі» / «Розділові» міняють межі уривків, але не літери)."""
    before = sum(ch.isalpha() for c in old[:idx] for ch in c)
    seen = 0
    for i, c in enumerate(new):
        seen += sum(ch.isalpha() for ch in c)
        if seen > before:
            return i
    return max(0, len(new) - 1)


def pick_quote(quotes: list[dict], letters, rng: random.Random, last: dict | None = None) -> dict | None:
    """Випадкова цитата, яку можна набрати літерами розкладки (не та сама, що щойно)."""
    ok = [q for q in quotes if set(quote_text(q)) <= set(letters) | {" "}]   # перевірка — за літерами
    if len(ok) > 1 and last in ok:
        ok.remove(last)
    return rng.choice(ok) if ok else None


def missing_letters(quote: dict, letters) -> str:
    """Літери цитати, яких нема серед letters (як фільтр у pick_quote); "" — набирається."""
    return "".join(sorted(set(quote_text(quote)) - set(letters) - {" "}))


def _search_words(text: str) -> list[str]:
    """Слова для пошуку: normalize + без апострофів («п’ять» = «п'ять» = «пять»)."""
    return normalize(text).replace("'", "").split()


def search_quotes(quotes: list[dict], query: str) -> list[dict]:
    """Цитати, де КОЖНЕ слово запиту — початок якогось слова тексту, автора чи твору
    («ліс» знайде «лісова», «лісі»; «франко лис» — лише Франкові з «лис…»). Регістр і
    апострофи не важать. Порожній запит — усі. Порядок — як у quotes."""
    words = _search_words(query)
    if not words:
        return list(quotes)
    found = []
    for q in quotes:
        hay = _search_words(" ".join((q.get("text", ""), q.get("author", ""), q.get("work", ""))))
        if all(any(h.startswith(w) for h in hay) for w in words):
            found.append(q)
    return found


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
    (за частотою) разом із , і . (WORD_PUNCT — відкриваються, як літери, навіть якщо на
    домашньому ряді). chars — {position_id: літера} з дошки."""
    rows = {p["id"]: p["row"] for p in geometry["positions"]}
    letters = {pid: ch for pid, ch in chars.items() if ch in ALPHABET or ch in WORD_PUNCT}
    freq = lambda ch: -unigrams.get(ch, 0)
    home = sorted({ch for pid, ch in letters.items() if rows.get(pid) == 1 and ch in ALPHABET}, key=freq)
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

    def pseudo_word(self, allowed: set[str], focus: str | None = None, start: str = "") -> str:
        """Псевдослово 3–7 літер ланцюжком Маркова за біграмами корпусу
        (start — готовий початок, напр. поєднання для «Поєднання»)."""
        letters = sorted(allowed - {"'"} - set(WORD_PUNCT))
        length = max(self.rng.randint(3, 7), len(start) + 1)
        word = start or (focus if focus and focus in letters and self.rng.random() < 0.5 else None)
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
             chars: int = LINE_CHARS, weak=()) -> str:
        """weak — слабкі літери: слова з ними у WEAK_WEIGHT разів частіше.
        Відкриті , і . — після слів (PUNCT_AFTER; нові чи слабкі — частіше)."""
        allowed = set(allowed)
        marks = [(m, PUNCT_FOCUS if m == focus or m in weak else p)
                 for m, p in PUNCT_AFTER.items() if m in allowed]
        real = self._real(allowed)
        weak = set(weak)
        weighted = [(w, n * (FOCUS_WEIGHT if focus and focus in w else 1.0)
                     * (WEAK_WEIGHT if weak & set(w) else 1.0)) for w, n in real]
        out, length, last = [], 0, None
        while length < chars:
            use_real = weighted and (len(weighted) >= MIN_REAL_WORDS or self.rng.random() < 0.3)
            if use_real:
                w = self.rng.choices([w for w, _ in weighted], [n for _, n in weighted])[0]
            else:
                w = self.pseudo_word(allowed, focus)
            if w == last and len(weighted) > 1:
                continue
            last = w
            for m, p in marks:
                if self.rng.random() < p:
                    w += m
                    break
            out.append(w)
            length += len(w) + 1
        return " ".join(out)


    def ngram_line(self, targets: list[tuple[str, float]], allowed: list[str] | set[str],
                   chars: int = LINE_CHARS) -> str:
        """Рядок для «Поєднання»: на кожне вибране (за вагою) поєднання — REPEAT слів
        поспіль, у яких воно є (з цитат; нема — псевдослово, що з нього починається)."""
        allowed = set(allowed)
        real = self._real(allowed)
        by_target = {t: [(w, n) for w, n in real if t in w] for t, _ in targets}
        out, length, last = [], 0, None
        while length < chars and targets:
            t = self.rng.choices([t for t, _ in targets], [w for _, w in targets])[0]
            if t == last and len(targets) > 1:
                continue
            last = t
            words = by_target[t]
            for _ in range(self.rng.randint(*REPEAT)):
                if words and self.rng.random() < 0.8:
                    w = self.rng.choices([w for w, _ in words], [n ** 0.5 for _, n in words])[0]
                else:
                    w = self.pseudo_word(allowed, start=t)
                out.append(w)
                length += len(w) + 1
        return " ".join(out)


def hard_targets(penalties: list[tuple[str, float]], allowed, top: int = HARD_TOP) -> list[tuple[str, float]]:
    """Найважчі поєднання з відкритих літер: [(n-грама, вага)], ваги в сумі 1.
    penalties — з MovementScoringEngine.ngram_penalty (біграми й триграми разом).
    Поєднання з однієї літери двічі (нн) — лише якщо інших мало."""
    allowed = set(allowed) - {"'"} - set(WORD_PUNCT)
    ok = [(g, v) for g, v in penalties if set(g) <= allowed]
    varied = [(g, v) for g, v in ok if len(set(g)) > 1]
    chosen = sorted(varied if len(varied) >= top // 2 else ok, key=lambda x: -x[1])[:top]
    # корінь — щоб перше поєднання не з'їдало весь рядок
    weights = [v ** 0.5 for _, v in chosen]
    total = sum(weights) or 1.0
    return [(g, w / total) for (g, _), w in zip(chosen, weights)]


# ----------------------------------------------------------------------
# Статистика по літерах між сесіями
# ----------------------------------------------------------------------
def _stats_path() -> Path:
    return user_data_dir() / STATS_FILE


def load_stats(geometry_name: str) -> dict:
    """{літера: {"hits", "misses", "ms", "timed"}} для геометрії (порожньо, якщо файлу нема)."""
    try:
        data = json.loads(_stats_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    stats = data.get(geometry_name, {}) if isinstance(data, dict) else {}
    return stats if isinstance(stats, dict) else {}


def save_stats(geometry_name: str, stats: dict) -> None:
    try:
        data = json.loads(_stats_path().read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data[geometry_name] = stats
    try:
        _stats_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def merge_stats(stats: dict, session: "Session") -> dict:
    """Додає натискання сесії до статистики (на місці; повертає її ж)."""
    for ch in set(session.hits) | set(session.misses):
        rec = stats.setdefault(ch, {"hits": 0, "misses": 0, "ms": 0, "timed": 0})
        rec["hits"] += session.hits[ch]
        rec["misses"] += session.misses[ch]
        rec["ms"] += round(session.time_ms[ch])
        rec["timed"] += session.timed[ch]
    return stats


def weak_letters(stats: dict, letters=None, n: int = 5) -> list[tuple[str, float, float | None]]:
    """Найслабші літери: [(літера, точність %, середній час мс або None)], від найгіршої.
    Слабкість — частка помилок, а при рівній — повільніша. Лише з ≥ MIN_SAMPLES натискань."""
    out = []
    for ch, rec in stats.items():
        if letters is not None and ch not in letters:
            continue
        total = rec.get("hits", 0) + rec.get("misses", 0)
        if total < MIN_SAMPLES or ch == " ":
            continue
        acc = 100.0 * rec.get("hits", 0) / total
        ms = rec["ms"] / rec["timed"] if rec.get("timed") else None
        out.append((ch, acc, ms))
    slow = sorted(ms for _, _, ms in out if ms is not None)
    median = slow[len(slow) // 2] if slow else 1.0
    # бал: помилки (у % пунктах) + повільність відносно медіани (×10 = 10% повільніше ~ 1 п.п.)
    score = lambda x: (100.0 - x[1]) + (10.0 * (x[2] / median - 1.0) if x[2] else 0.0)
    return sorted(out, key=score, reverse=True)[:n]


def should_level_up(lines: list[tuple[float, float]]) -> bool:
    """«Сам підвищуй»: останні LEVEL_UP_LINES рядків поточного рівня — кожен з точністю
    ≥ LEVEL_UP_ACCURACY і швидкість стабільна (розкид ≤ LEVEL_UP_SPREAD від середньої)."""
    if len(lines) < LEVEL_UP_LINES:
        return False
    last = lines[-LEVEL_UP_LINES:]
    cpms = [c for c, _ in last]
    mean = sum(cpms) / len(cpms)
    return (all(a >= LEVEL_UP_ACCURACY for _, a in last) and mean > 0
            and (max(cpms) - min(cpms)) / mean <= LEVEL_UP_SPREAD)


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

for i, q in enumerate("1234567890-="):
    vk = ord(q) if q.isdigit() else {"-": 0xBD, "=": 0xBB}[q]
    _ROWS[f"AE{i + 1:02d}"] = (10 + i, vk, q, q)

X11_KEYCODES = {v[0]: k for k, v in _ROWS.items()}
WIN_VK = {v[1]: k for k, v in _ROWS.items()}
BY_CHAR = {**{v[2]: k for k, v in _ROWS.items() if not k.startswith("AE")},
           **{v[3]: k for k, v in _ROWS.items() if not k.startswith("AE")},
           **{v[2]: k for k, v in _ROWS.items() if k.startswith("AE")}}
BY_CHAR.update({ch.upper(): k for ch, k in list(BY_CHAR.items()) if ch.isalpha()})

# біти event.state, що означають AltGr / Alt (Tk): X11 — Mod1 (Alt) і Mod5 (ISO_Level3);
# Windows — Alt (0x20000; AltGr приходить як Ctrl+Alt)
ALTGR_MASK = {"x11": 0x08 | 0x80, "win32": 0x20000}
SPACE_KEYCODE = {"x11": 65, "win32": 0x20}


def key_outputs(ch: str, altgr: dict) -> set[str]:
    """Що дає клавіша з символом ch (без Shift, з Shift, AltGr) — для підсвітки на схемі
    наступного знака (: — це Shift на клавіші з ., ґ — AltGr на г). Малими: схема без регістру."""
    from core import export
    out = {ch, export._shifted(ch)} if ch else set()
    if altgr.get(ch):
        out.add(altgr[ch])
    return {c.lower() for c in out if c}


def can_translate(geometry: dict) -> bool:
    return any(p.get("key") for p in geometry["positions"])


@dataclass
class Translator:
    chars: dict[int, str]            # {position_id: літера} з дошки
    geometry: dict
    windowing: str = "x11"           # root.tk.call("tk", "windowingsystem"): x11 / win32 / aqua

    def __post_init__(self):
        from core import export
        try:   # {клавіша: [без модифікатора, Shift, AltGr, Shift+AltGr]} — як в експорті
            self.levels = export.keymap(self.chars, self.geometry)
        except ValueError:   # розкладка неповна — лише літерні клавіші
            altgr = self.geometry.get("altgr", {})
            self.levels = {}
            for p in self.geometry["positions"]:
                ch = self.chars.get(p["id"], "")
                if p.get("key") and ch:
                    third = altgr.get(ch)
                    self.levels[p["key"]] = [ch, ch.upper(), third, third.upper() if third else None]

    def physical_key(self, keycode: int, char: str) -> str | None:
        table = X11_KEYCODES if self.windowing == "x11" else WIN_VK if self.windowing == "win32" else {}
        return table.get(keycode) or BY_CHAR.get(char)

    def translate(self, keycode: int, char: str, state: int) -> str | None:
        """Символ нової розкладки для натискання (з урахуванням Shift і AltGr)
        або None (клавіша без символу: Shift, Ctrl…)."""
        if char == " " or keycode == SPACE_KEYCODE.get(self.windowing):
            return " "
        key = self.physical_key(keycode, char)
        levels = self.levels.get(key) if key else None
        if not levels:
            return None
        level = (1 if state & SHIFT_MASK else 0) + (2 if state & ALTGR_MASK.get(self.windowing, 0) else 0)
        ch = levels[level] or (levels[level - 1] if level == 3 else None)
        return ch or None


def as_is(char: str) -> str | None:
    """Без перекладу: символ, який дала система (нормалізовані апострофи)."""
    if not char:
        return None
    ch = char.translate(_APOSTROPHES).translate(_PUNCT_MAP)
    return ch if ch.lower() in ALPHABET or ch == " " or ch in PUNCT else None


def fit(ch: str | None, caps: bool) -> str | None:
    """Натиснутий символ під налаштування вправи: без «Великих» велика = мала
    (зайвий Shift не карається). Розділовий лишається як є — у тексті без них це помилка."""
    if ch is None:
        return None
    return ch if caps else ch.lower()


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
    hits: Counter = field(default_factory=Counter)    # літера -> набрано правильно з першого разу
    time_ms: Counter = field(default_factory=Counter)  # літера -> сума часу до неї (мс)
    timed: Counter = field(default_factory=Counter)    # ... скільки натискань у цій сумі
    started: float | None = None
    finished: float | None = None
    last_ok: float | None = None

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
            if ch != " ":
                key = ch.lower()
                if self.pos not in self.wrong_at:
                    self.hits[key] += 1
                # час від попередньої правильної літери; після помилки чи паузи — не рахуємо
                if (self.last_ok is not None and self.pos not in self.wrong_at
                        and now - self.last_ok <= PAUSE_S):
                    self.time_ms[key] += 1000.0 * (now - self.last_ok)
                    self.timed[key] += 1
            self.last_ok = now
            self.pos += 1
            if self.done:
                self.finished = now
            return True
        self.errors += 1
        if self.pos not in self.wrong_at and self.text[self.pos] != " ":
            self.misses[self.text[self.pos].lower()] += 1       # одна позиція — одна помилка в статистиці
        self.wrong_at.add(self.pos)
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
