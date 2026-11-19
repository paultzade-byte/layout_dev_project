"""Частотний словник слів для оцінки серій натискань однією рукою (hand runs).

Біграми/триграми не бачать серій довших за 3 натискання, а саме вони
перевантажують руку (приклад: слово, яке повністю набирається однією рукою).
Тому scorer оцінює альтернацію рук по цілих словах, а цей скрипт готує для
нього config/word_stats.json.

Нормалізація збігається з лічильником n-грам: текст -> lower(), словом
вважається максимальна послідовність українських літер та апострофа "'".
Усе інше (зокрема ’ і ʼ) — роздільник, як і в statistic.json.

Корпус (~16 ГБ) не читається повністю: з кожного файлу береться рівномірна
вибірка шматків, пропорційна розміру файлу (SAMPLE_FRACTION), тож пропорції
джерел ті самі, що й у statistic.json.

Запуск з кореня проєкту:
    python scripts/word_counter.py
"""

import json
import os
import re
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

PROJ_DIR = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJ_DIR / ".ignore_storage" / "dirty_data"
OUTPUT_PATH = PROJ_DIR / "config" / "word_stats.json"

SAMPLE_FRACTION = 0.04          # частка кожного файлу, що потрапляє у вибірку
CHUNK_BYTES = 4 * 1024 * 1024   # розмір одного шматка вибірки
TOP_WORDS = 50_000              # скільки найчастіших слів зберегти
MIN_WORD_LEN = 2                # однолітерні слова не мають серій — їх штраф сталий
WORKERS = 4
WORKER_NICE = 15                # поступливий пріоритет, як у лічильнику n-грам

_WORD_RE = re.compile(r"[абвгґдеєжзиіїйклмнопрстуфхцчшщьюя']+")


def build_tasks(files):
    tasks = []
    for path in files:
        size = path.stat().st_size
        n_chunks = max(1, int(size * SAMPLE_FRACTION / CHUNK_BYTES))
        step = size // n_chunks
        tasks.extend((str(path), i * step) for i in range(n_chunks))
    return tasks


def init_worker():
    os.nice(WORKER_NICE)


def count_chunk(task):
    path, offset = task
    with open(path, "rb") as f:
        f.seek(offset)
        raw = f.read(CHUNK_BYTES)
    # обрізаємо по пробілах з обох боків, щоб не рахувати половинки слів
    # (і не різати багатобайтові символи UTF-8)
    first, last = raw.find(b" "), raw.rfind(b" ")
    if first == -1 or first >= last:
        return Counter()
    text = raw[first:last].decode("utf-8", errors="ignore").lower()
    words = (w.strip("'") for w in _WORD_RE.findall(text))
    return Counter(w for w in words if len(w) >= MIN_WORD_LEN)


def main():
    files = sorted(CORPUS_DIR.glob("*.txt"))
    if not files:
        sys.exit(f"no corpus files in {CORPUS_DIR}")
    tasks = build_tasks(files)
    total = Counter()
    with Pool(WORKERS, initializer=init_worker) as pool:
        for done, counts in enumerate(pool.imap_unordered(count_chunk, tasks), 1):
            total.update(counts)
            print(f"\r{done}/{len(tasks)} chunks", end="", flush=True)
    print()

    top = total.most_common(TOP_WORDS)
    covered = sum(n for _, n in top)
    meta = {
        "sample_fraction": SAMPLE_FRACTION,
        "tokens_seen": sum(total.values()),
        "unique_words_seen": len(total),
        "top_words": len(top),
        "top_coverage": round(covered / max(sum(total.values()), 1), 4),
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "words": dict(top)}, f, ensure_ascii=False, indent=0)
    print(meta)


if __name__ == "__main__":
    main()
