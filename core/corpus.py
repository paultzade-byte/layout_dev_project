"""Статистика корпусу текстів -> statistic.json + word_stats.json.

Один прохід по корпусу (теці з .txt, з підтеками) рахує все, що потрібно
оптимізатору:
- уні/бі/три/скіп-грами символів алфавіту мови (statistic.json);
- частоти слів для hand_runs (word_stats.json) — з рівномірної вибірки
  кожного шматка (sample_fraction у meta; main_config масштабує назад).

Код підрахунку перенесено з scripts/ngram_counter.py і scripts/word_counter.py
(ті лишились тонкими CLI-обгортками); результат на тому самому корпусі —
той самий, крім апострофів (див. normalize_apostrophes).

Мова (алфавіт) — параметр: LANGUAGES. detect_language() вгадує її за
характерними літерами з початку кількох файлів.

Обмеження CPU — частка всієї машини (cpu_share 0..1): кількість воркерів +
паузи всередині кожного воркера (як CPU_LOAD_FRACTION у старому лічильнику),
плюс os.nice. Працює однаково в Linux і Windows, без cpulimit.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Callable

import numpy as np

# ---------------------------------------------------------------- мови

DIGITS = "0123456789"
PUNCTUATION = " .,!?;:()-—«»\"'\n\t"


@dataclass(frozen=True)
class Language:
    code: str
    tag: str              # у назві файлу статистики: ukr_…json (ISO 639-2)
    name: str
    letters: str          # малі літери алфавіту (апостроф — окремо, у PUNCTUATION)
    markers: str          # літери, за якими мову видно серед сусідніх
    apostrophe: bool      # чи апостроф — частина слова (для словника слів)


LANGUAGES = {
    "uk": Language("uk", "ukr", "Українська", "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя", "ґєї", True),
    "be": Language("be", "bel", "Білоруська", "абвгдеёжзійклмнопрстуўфхцчшыьэюя", "ў", True),
    "pl": Language("pl", "pol", "Польська", "aąbcćdeęfghijklłmnńoóprsśtuwyzźżqvx", "ąćęłńśźż", False),
}

# Апострофи, які в текстах трапляються замість "'" (вибірка UberText 2026-11-24:
# ' 22 435, ’ 7 610, ‘ 689, ʼ 101, ` 70 — між двома літерами). Зводимо до "'"
# лише між літерами: ‘лапки’ навколо слова лишаються лапками (-> пробіл).
APOSTROPHE_VARIANTS = "’‘ʼ`´ʹʻ′＇‛"
# «літера» — без апострофів: ʼ ʹ ʻ у Unicode — літери-модифікатори (Lm) і інакше
# рахувалися б межею слова. Кілька апострофів підряд (п’’ять, пʼ’ять, п'’ять) -> один "'".
_LETTER = rf"[^\W\d_{APOSTROPHE_VARIANTS}]"
_APOSTROPHE_RE = re.compile(rf"(?<={_LETTER})['{APOSTROPHE_VARIANTS}]+(?={_LETTER})")


def normalize_apostrophes(text: str) -> str:
    """’ ‘ ʼ ` ´ … (одна чи кілька підряд) між двома літерами -> "'"."""
    return _APOSTROPHE_RE.sub("'", text)


def detect_language(files: list[Path], sample_bytes: int = 1_000_000) -> str | None:
    """Код мови з найбільшою часткою характерних літер на початку файлів
    (до 20 файлів по sample_bytes); None — якщо жодної не видно."""
    hits = Counter()
    for path in files[:20]:
        with open(path, "rb") as f:
            text = f.read(sample_bytes).decode("utf-8", errors="ignore").lower()
        for code, lang in LANGUAGES.items():
            hits[code] += sum(text.count(ch) for ch in lang.markers)
    if not hits or hits.most_common(1)[0][1] == 0:
        return None
    return hits.most_common(1)[0][0]


def check_utf8(files, sample_bytes: int = 1 << 16) -> None:
    """ValueError, якщо початок якогось файлу — не UTF-8 (напр. cp1251): інакше
    decode(errors="ignore") мовчки викинув би всю кирилицю і статистика була б порожня."""
    for path in map(Path, files):
        with open(path, "rb") as f:
            raw = f.read(sample_bytes)
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            if len(raw) == sample_bytes and e.start >= len(raw) - 3:
                continue  # вибірка розрізала останню літеру — це не помилка кодування
            raise ValueError(f"{path.name}: файл не в UTF-8 (може, cp1251?) — "
                             "збережи його в кодуванні UTF-8") from None


def find_corpus_files(paths) -> list[Path]:
    """Усі .txt у вибраних теках (з підтеками) і вибрані .txt-файли."""
    out = []
    for p in map(Path, [paths] if isinstance(paths, (str, Path)) else paths):
        if p.is_dir():
            out.extend(sorted(q for q in p.rglob("*") if q.is_file() and q.suffix.lower() == ".txt"))
        elif p.is_file() and p.suffix.lower() == ".txt":
            out.append(p)
    return out


# ---------------------------------------------------------------- алфавіт

class Alphabet:
    def __init__(self, lang: Language):
        self.lang = lang
        self.chars = lang.letters + DIGITS + PUNCTUATION
        assert len(set(self.chars)) == len(self.chars), "у алфавіті є дублікати символів"
        self.size = len(self.chars)
        space = self.chars.index(" ")
        self.lookup = np.full(0x10000, space, dtype=np.uint8)
        for i, ch in enumerate(self.chars):
            self.lookup[ord(ch)] = i
        word_chars = re.escape(lang.letters + ("'" if lang.apostrophe else ""))
        self.word_re = re.compile(f"[{word_chars}]+")

    def to_ids(self, text: str) -> np.ndarray:
        """Символ -> id; усе поза алфавітом (і все поза BMP) — пробіл."""
        if not text:
            return np.empty(0, dtype=np.uint8)
        cps = np.frombuffer(text.encode("utf-32-le"), dtype=np.uint32)
        return self.lookup[np.minimum(cps, 0xFFFF)]


def ngram_counts(ids: np.ndarray, size: int):
    """Бі/три/скіп-грами одного шматка: біграми — усі пари (від 2 символів),
    три- і скіп-грами — від 3 символів."""
    n = len(ids)
    bi = np.zeros(size ** 2, dtype=np.int64)
    tri = np.zeros(size ** 3, dtype=np.int64)
    skip = np.zeros(size ** 2, dtype=np.int64)
    if n >= 2:
        ab = ids[:n - 1].astype(np.uint32) * size + ids[1:].astype(np.uint32)
        bi += np.bincount(ab, minlength=size ** 2)
    if n >= 3:
        a = ids[:n - 2].astype(np.uint32)
        c = ids[2:].astype(np.uint32)
        skip += np.bincount(a * size + c, minlength=size ** 2)
        tri += np.bincount(ab[:n - 2] * size + c, minlength=size ** 3)
    return bi, tri, skip


# ---------------------------------------------------------------- нарізка

TASK_BYTES = 50 * 1024 * 1024


def _safe_boundary(path: Path, offset: int) -> int:
    """Зсув уперед до початку символу UTF-8 (не різати кирилицю навпіл)."""
    if offset <= 0:
        return 0
    with open(path, "rb") as f:
        f.seek(offset)
        for i, b in enumerate(f.read(4)):
            if (b & 0xC0) != 0x80:
                return offset + i
    return offset


def build_tasks(files, task_bytes: int = TASK_BYTES):
    tasks = []
    for path in files:
        size = path.stat().st_size
        bounds = sorted({0, size, *(_safe_boundary(path, b) for b in range(task_bytes, size, task_bytes))})
        tasks.extend((str(path), s, e) for s, e in zip(bounds, bounds[1:]) if e > s)
    return tasks


# ---------------------------------------------------------------- воркер

_W: dict = {}


def _init_worker(lang_code: str, duty: float, sample_fraction: float, nice: int):
    import signal
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C обробляє головний процес
    except (ValueError, AttributeError):
        pass
    try:
        os.nice(nice)
    except (AttributeError, OSError):
        pass
    _W.update(alpha=Alphabet(LANGUAGES[lang_code]), duty=duty, frac=sample_fraction)


def _process(task):
    path, start, end = task
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        f.seek(start)
        raw = f.read(end - start)
    text = raw.decode("utf-8", errors="ignore").lower()
    # переноси Windows (\r\n) і старого Mac (\r) -> \n, інакше \r став би зайвим пробілом
    text = normalize_apostrophes(text.replace("\r\n", "\n").replace("\r", "\n"))
    alpha: Alphabet = _W["alpha"]
    ids = alpha.to_ids(text)
    chars = np.bincount(ids, minlength=alpha.size)
    bi, tri, skip = ngram_counts(ids, alpha.size)

    # слова — з початку шматка, частка frac; межі — по пробілу (без половинок слів)
    words = Counter()
    if _W["frac"] > 0:
        part = text[:max(1, int(len(text) * _W["frac"]))] if _W["frac"] < 1 else text
        cut = part.rfind(" ") if _W["frac"] < 1 else len(part)
        tokens = (w.strip("'") for w in alpha.word_re.findall(part[:cut]))
        words.update(w for w in tokens if len(w) >= MIN_WORD_LEN)

    duty = _W["duty"]
    if 0 < duty < 1:
        time.sleep((time.perf_counter() - t0) * (1 - duty) / duty)
    return chars, bi, tri, skip, words, end - start


# ---------------------------------------------------------------- запуск

MIN_WORD_LEN = 2            # однолітерні слова не мають серій
TOP_WORDS = 50_000
WORD_SAMPLE_BYTES = 650 * 1024 * 1024   # ≈ 4% корпусу UberText; менший корпус — весь
# поріг відсіву рідкісних n-грам — частка від кількості символів; на UberText
# (~8 млрд символів) дає ті самі 100, що були константою MIN_NGRAM_COUNT
MIN_NGRAM_SHARE = 1.25e-8
WORKER_NICE = 15


@dataclass
class Progress:
    bytes_done: int
    bytes_total: int
    tasks_done: int
    tasks_total: int
    elapsed: float

    @property
    def fraction(self) -> float:
        return self.bytes_done / self.bytes_total if self.bytes_total else 1.0


class Stopped(Exception):
    """Підрахунок зупинено (should_stop)."""


def worker_plan(cpu_share: float, cores: int | None = None) -> tuple[int, float]:
    """cpu_share (частка всієї машини) -> (кількість воркерів, частка часу роботи кожного)."""
    cores = cores or os.cpu_count() or 1
    budget = max(0.05, min(1.0, cpu_share)) * cores
    workers = max(1, min(cores, math.ceil(budget)))
    return workers, min(1.0, budget / workers)


def count_corpus(files, lang_code: str, cpu_share: float = 0.25,
                 progress: Callable[[Progress], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> dict:
    """Рахує статистику; повертає {"statistic": ..., "words": ..., "meta": ...}.
    Зупинка (should_stop() -> True) — виняток Stopped, нічого не пишеться."""
    files = [Path(f) for f in files]
    if not files:
        raise ValueError("немає .txt файлів")
    check_utf8(files)
    alpha = Alphabet(LANGUAGES[lang_code])
    tasks = build_tasks(files)
    total_bytes = sum(e - s for _, s, e in tasks)
    frac = min(1.0, WORD_SAMPLE_BYTES / max(total_bytes, 1))
    workers, duty = worker_plan(cpu_share)

    chars = np.zeros(alpha.size, dtype=np.int64)
    bi = np.zeros(alpha.size ** 2, dtype=np.int64)
    tri = np.zeros(alpha.size ** 3, dtype=np.int64)
    skip = np.zeros(alpha.size ** 2, dtype=np.int64)
    words = Counter()
    done = nbytes = 0
    t0 = time.perf_counter()

    ctx = get_context("spawn")      # однаково в Linux, Windows і зібраному exe
    pool = ctx.Pool(workers, initializer=_init_worker,
                    initargs=(lang_code, duty, frac, WORKER_NICE))
    try:
        for c, b, t, s, w, n in pool.imap_unordered(_process, tasks):
            chars += c; bi += b; tri += t; skip += s
            words.update(w)
            done += 1
            nbytes += n
            if progress:
                progress(Progress(nbytes, total_bytes, done, len(tasks), time.perf_counter() - t0))
            if should_stop and should_stop():
                pool.terminate()
                raise Stopped()
        pool.close()
    finally:
        pool.terminate()
        pool.join()

    if not chars[:len(alpha.lang.letters)].any():
        raise ValueError(f"у корпусі немає жодної літери мови «{lang_code}» — "
                         "перевір файли й мову; нічого не записано")
    min_count = max(2, round(int(chars.sum()) * MIN_NGRAM_SHARE))
    for arr in (bi, tri, skip):
        arr[arr <= min_count] = 0
    statistic = _to_statistic(alpha, chars, bi, tri, skip)

    top = words.most_common(TOP_WORDS)
    seen = sum(words.values())
    meta = {
        "language": lang_code,
        "sample_fraction": frac,
        "tokens_seen": seen,
        "unique_words_seen": len(words),
        "top_words": len(top),
        "top_coverage": round(sum(n for _, n in top) / max(seen, 1), 4),
        "files": len(files),
        "bytes": total_bytes,
        "min_ngram_count": min_count,
    }
    return {"statistic": statistic, "words": dict(top), "meta": meta}


def _to_statistic(alpha: Alphabet, chars, bi, tri, skip) -> dict:
    ch, n = alpha.chars, alpha.size

    def pairs(arr):
        idx = np.nonzero(arr)[0]
        return {ch[i // n] + ch[i % n]: int(arr[i]) for i in idx[np.argsort(-arr[idx], kind="stable")]}

    tri_idx = np.nonzero(tri)[0]
    tri_idx = tri_idx[np.argsort(-tri[tri_idx], kind="stable")]
    uni_idx = np.nonzero(chars)[0]
    uni_idx = uni_idx[np.argsort(-chars[uni_idx], kind="stable")]
    return {
        "unigrams": {ch[i]: int(chars[i]) for i in uni_idx},
        "bigrams": pairs(bi),
        "trigrams": {ch[i // (n * n)] + ch[i // n % n] + ch[i % n]: int(tri[i]) for i in tri_idx},
        "skipgrams": pairs(skip),
    }


def statistic_file_name(lang_code: str, corpus_name: str, day: str | None = None) -> str:
    """ukr_<корпус>_2026-11-24.json — мова видна з назви (вибір в оптимізаторі)."""
    from datetime import date
    safe = re.sub(r"[^\w.-]+", "_", corpus_name).strip("_.")[:40] or "тексти"
    return f"{LANGUAGES[lang_code].tag}_{safe}_{day or date.today().isoformat()}.json"


def write_statistic_file(result: dict, out_dir, corpus_name: str) -> Path:
    """Один файл: n-грами + words + meta (мова, корпус, дата). Такі файли
    оптимізатор показує в меню «Статистика ▾» (config/stats_files.py).
    Той самий день і корпус — файл перезаписується."""
    from datetime import datetime
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {**result["meta"], "corpus": corpus_name, "created": datetime.now().isoformat(timespec="minutes")}
    path = out_dir / statistic_file_name(meta["language"], corpus_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, **result["statistic"], "words": result["words"]}, f, ensure_ascii=False)
    return path


def write_outputs(result: dict, out_dir) -> tuple[Path, Path]:
    """statistic.json і word_stats.json у out_dir — вбудована статистика оптимізатора
    (config/, формат, який читає main_config)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stat_path, words_path = out_dir / "statistic.json", out_dir / "word_stats.json"
    with open(stat_path, "w", encoding="utf-8") as f:
        json.dump(result["statistic"], f, ensure_ascii=False, indent=4)
    with open(words_path, "w", encoding="utf-8") as f:
        json.dump({"meta": result["meta"], "words": result["words"]}, f, ensure_ascii=False, indent=0)
    return stat_path, words_path
