"""
Швидкий char/n-gram лічильник для корпусу UberText -- версія з динамічним
розподілом роботи (work-stealing) між ядрами.

Відмінність від попередньої версії (один процес на файл): файли ріжуться на
задачі фіксованого розміру (~TASK_SIZE_MB кожна), і спільний пул воркерів
(за кількістю ядер) забирає задачі з черги по мірі звільнення -- незалежно
від того, з якого файлу задача. Коли маленький файл закінчується, звільнене
ядро одразу підхоплює шматок файлу, що ще обробляється, замість того щоб
простоювати або лишати останній файл на одному ядрі.

Побічний ефект цієї зміни: shared memory більше не потрібна. Задач на весь
корпус ~500-700 (замість тисяч чанків), тому можна просто повертати результат
кожної задачі напряму через Pool.imap_unordered -- дешевше і простіше коду.

Компроміс: при перериванні (Ctrl+C) втрачається прогрес задач, що саме
виконуються в момент сигналу (до TASK_SIZE_MB на кожне зайняте ядро), а не
~1 МБ як у попередній версії. Свідомий вибір заради кращого розмазування
навантаження під кінець прогону.

Звідси — `config/statistic.json` (уні/бі/три/скіп-грами; разом зі
`scripts/word_counter.py` для частот слів). Раніше лежав у корені як
`.ignore_counter_worksteal.py`. Запуск — з кореня проєкту, під квотою CPU
(див. CLAUDE.md). Шлях до корпусу поки зашитий (CORPUS_DIR) — для міні-апки
статистики треба вибір шляху юзером (WORKLOG «Наступні кроки» -6).
"""

import os
import signal
import sys
import time
from collections import Counter
from pathlib import Path
from datetime import datetime
from multiprocessing import Pool, cpu_count
import json
import numpy as np

PROJ_DIR = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJ_DIR / ".ignore_storage" / "dirty_data"  # TODO: вибір шляху (WORKLOG -6)

# ~~~~~~~~~~~~~~~~~~~~~~~ #
#         config          #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
TASK_SIZE_MB = 50
TASK_SIZE_BYTES = TASK_SIZE_MB * 1024 * 1024

# Вбудований самообмежувач навантаження -- НЕ залежить від того, чи хтось запустить
# cpulimit ззовні з правильними прапорцями (cpulimit -p без --include-children взагалі
# не працює для multiprocessing, бо стежить лише за головним процесом, а не за воркерами).
# CPU_LOAD_FRACTION -- частка часу, яку кожен воркер РЕАЛЬНО рахує, решту він спить.
# 1.0 = без обмежень (максимальна швидкість). 0.6 = кожен воркер рахує ~60% часу,
# ~40% спить -- помітно менше тепла, невелика втрата швидкості. Підбирай під своє
# охолодження; для утиліти, яку віддаєш іншим людям, безпечніше лишити < 1.0 за замовчуванням.
CPU_LOAD_FRACTION = 0.3 # 0.7
WORKER_NICE = 15 # 10 поступливий пріоритет (0..19, вище = поступливіший) -- не заважає іншим програмам

UKR_LETTERS = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
DIGITS = "0123456789"
PUNCTUATION = " .,!?;:()-—«»\"'\n\t"
ALLOWED_CHARS = UKR_LETTERS + DIGITS + PUNCTUATION

assert len(set(ALLOWED_CHARS)) == len(ALLOWED_CHARS), "В ALLOWED_CHARS є дублікати символів"

ALPHABET_SIZE = len(ALLOWED_CHARS)
ID_TO_CHAR = list(ALLOWED_CHARS)
CHAR_TO_ID = {c: i for i, c in enumerate(ALLOWED_CHARS)}
SPACE_ID = CHAR_TO_ID[' ']

LOOKUP_SIZE = 0x10000
_lookup = np.full(LOOKUP_SIZE, SPACE_ID, dtype=np.uint8)
for _ch, _idx in CHAR_TO_ID.items():
    _cp = ord(_ch)
    if _cp < LOOKUP_SIZE:
        _lookup[_cp] = _idx

MAX_MONOGRAMS = 200
MAX_BIGRAMS = 100_000
MAX_TRIGRAMS = 500_000
MAX_SKIPGRAMS = 150_000
MIN_NGRAM_COUNT = 100


# ~~~~~~~~~~~~~~~~~~~~~~~ #
#   векторизований core   #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
def text_to_ids(text: str) -> np.ndarray:
    """Символ -> id, векторизовано. Все поза allowlist (і всі емодзі) стає id пробілу."""
    if not text:
        return np.empty(0, dtype=np.uint8)
    codepoints = np.frombuffer(text.encode('utf-32-le'), dtype=np.uint32)
    codepoints = np.minimum(codepoints, LOOKUP_SIZE - 1)
    return _lookup[codepoints]


def ngram_counts(ids: np.ndarray):
    """
    Векторизований підрахунок бі/три/скіп-грам для масиву id одного шматка тексту.
    Так само, як і в попередній версії: bigram навмисно не включає останню пару
    шматка -- на межах задач це дає мінімальну (нехтовно малу, ~1 пара на задачу
    з мільярдів) втрату точності, аналогічно до того, як і раніше губились
    поодинокі біграми на межах файлів. Свідомий компроміс заради швидкості.

    dtype-примітка: коди (a*ALPHABET+b і т.д.) використовують uint32, а не int64.
    ALPHABET_SIZE^3 (максимально можливий код триграми) із ~94 символами -- це
    ~830 тисяч, що вільно влазить у uint32 (до ~4.29 млрд). Використання int64
    тут раніше подвоювало пікову пам'ять на кожну задачу без жодної користі --
    саме це змушувало зменшувати розмір задачі, щоб уникнути OOM при кількох
    паралельних воркерах.
    """
    n = len(ids)
    bigram_counts = np.zeros(ALPHABET_SIZE ** 2, dtype=np.int64)
    trigram_counts = np.zeros(ALPHABET_SIZE ** 3, dtype=np.int64)
    skipgram_counts = np.zeros(ALPHABET_SIZE ** 2, dtype=np.int64)

    if n >= 3:
        a = ids[0:n - 2].astype(np.uint32)
        b = ids[1:n - 1].astype(np.uint32)
        c = ids[2:n].astype(np.uint32)

        bigram_codes = a * ALPHABET_SIZE + b
        skipgram_codes = a * ALPHABET_SIZE + c
        trigram_codes = bigram_codes * ALPHABET_SIZE + c

        bigram_counts += np.bincount(bigram_codes, minlength=ALPHABET_SIZE ** 2)
        skipgram_counts += np.bincount(skipgram_codes, minlength=ALPHABET_SIZE ** 2)
        trigram_counts += np.bincount(trigram_codes, minlength=ALPHABET_SIZE ** 3)

    return bigram_counts, trigram_counts, skipgram_counts

def apply_threshold(counts: np.ndarray, min_count: int) -> np.ndarray:
    """Обнуляє все, що менше за min_count, до конвертації в Counter,
    економить час на найбільйих масивах(trigram)"""
    filtered = counts.copy()
    filtered[filtered <= min_count] = 0
    return filtered

# ~~~~~~~~~~~~~~~~~~~~~~~ #
#     нарізка на задачі   #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
def find_safe_boundary(path: Path, approx_offset: int) -> int:
    """
    Зсуває приблизний офсет вперед до першого байта, який НЕ є continuation-байтом
    UTF-8 (тобто до початку валідного символу) -- щоб не розрізати багатобайтовий
    символ (кирилицю) навпіл між двома задачами.
    """
    if approx_offset <= 0:
        return 0
    with open(path, 'rb') as f:
        f.seek(approx_offset)
        chunk = f.read(4)  # символ UTF-8 максимум 4 байти
        for i, b in enumerate(chunk):
            if (b & 0xC0) != 0x80:  # не continuation byte -> це початок символу
                return approx_offset + i
    return approx_offset  # fallback, малоймовірно на реальних текстових даних


def build_tasks(files, task_size_bytes: int):
    """Ріже кожен файл на задачі по ~task_size_bytes, з UTF-8-безпечними межами."""
    tasks = []
    for f in files:
        size = f.stat().st_size
        raw_boundaries = list(range(0, size, task_size_bytes))
        if raw_boundaries[-1] != size:
            raw_boundaries.append(size)

        safe_boundaries = [0]
        for b in raw_boundaries[1:-1]:
            safe_boundaries.append(find_safe_boundary(f, b))
        safe_boundaries.append(size)
        safe_boundaries = sorted(set(safe_boundaries))

        for start, end in zip(safe_boundaries[:-1], safe_boundaries[1:]):
            if end > start:
                tasks.append((str(f), start, end))
    return tasks


# ~~~~~~~~~~~~~~~~~~~~~~~ #
#         worker          #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
def init_worker():
    # головний процес сам обробляє Ctrl+C і коректно гасить пул;
    # якщо воркери теж ловитимуть SIGINT, вихід стає безладним
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # поступливий пріоритет -- воркер завжди поступається системним і чужим процесам
    try:
        os.nice(WORKER_NICE)
    except (AttributeError, OSError):
        pass  # os.nice відсутній на деяких платформах (Windows) -- не критично


def process_task(task):
    file_path, start, end = task
    t0 = time.perf_counter()

    with open(file_path, 'rb') as f:
        f.seek(start)
        raw = f.read(end - start)
    text = raw.decode('utf-8', errors='ignore')
    text = text.lower()

    ids = text_to_ids(text)
    char_delta = np.bincount(ids, minlength=ALPHABET_SIZE)
    bigram_delta, trigram_delta, skipgram_delta = ngram_counts(ids)

    if 0 < CPU_LOAD_FRACTION < 1:
        work_time = time.perf_counter() - t0
        rest_time = work_time * (1 - CPU_LOAD_FRACTION) / CPU_LOAD_FRACTION
        time.sleep(rest_time)

    return char_delta, bigram_delta, trigram_delta, skipgram_delta, (end - start)


# ~~~~~~~~~~~~~~~~~~~~~~~ #
#     live progress UI    #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
BAR_WIDTH = 40


def render_progress(bytes_done: int, total_bytes: int, tasks_done: int, total_tasks: int) -> None:
    frac = min(bytes_done / total_bytes, 1.0) if total_bytes else 1.0
    filled = int(BAR_WIDTH * frac)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    sys.stdout.write(f"\r  [{bar}] {frac:6.1%}  (задач: {tasks_done}/{total_tasks})   ")
    sys.stdout.flush()


# ~~~~~~~~~~~~~~~~~~~~~~~ #
#       formatting        #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
def format_char(char: str) -> str:
    if char == '\n':
        return "Перенесення рядка (\\n)"
    elif char == '\t':
        return "Табуляція (\\t)"
    elif char == ' ':
        return "Пробіл (' ')"
    else:
        return f"Символ '{char}'"


def array_to_char_counter(counts: np.ndarray) -> Counter:
    nonzero = np.nonzero(counts)[0]
    return Counter({ID_TO_CHAR[i]: int(counts[i]) for i in nonzero})


def array_to_pair_counter(counts: np.ndarray) -> Counter:
    nonzero = np.nonzero(counts)[0]
    result = Counter()
    for code in nonzero:
        a, b = divmod(int(code), ALPHABET_SIZE)
        result[(ID_TO_CHAR[a], ID_TO_CHAR[b])] = int(counts[code])
    return result


def array_to_triple_counter(counts: np.ndarray) -> Counter:
    nonzero = np.nonzero(counts)[0]
    result = Counter()
    for code in nonzero:
        ab, c = divmod(int(code), ALPHABET_SIZE)
        a, b = divmod(ab, ALPHABET_SIZE)
        result[(ID_TO_CHAR[a], ID_TO_CHAR[b], ID_TO_CHAR[c])] = int(counts[code])
    return result


def write_char_report(out_f, char_freqs: Counter) -> None:
    out_f.write(f"Всього знайдено унікальних символів: {len(char_freqs)}\n")
    out_f.write(f"(у звіті показано перші {MAX_MONOGRAMS})\n")
    out_f.write("-" * 40 + "\n")
    for char, count in char_freqs.most_common(MAX_MONOGRAMS):
        out_f.write(f"{format_char(char)}: {count}\n")


def write_bigram_report(out_f, bigrams: Counter) -> None:
    out_f.write(f"\nВсього знайдено унікальних біграм: {len(bigrams)}\n")
    out_f.write(f"(у звіті показано перші {MAX_BIGRAMS})\n")
    out_f.write("-" * 40 + "\n")
    for (a, b), count in bigrams.most_common(MAX_BIGRAMS):
        out_f.write(f"{format_char(a)} + {format_char(b)}: {count}\n")


def write_trigram_report(out_f, trigrams: Counter) -> None:
    out_f.write(f"\nВсього знайдено унікальних триграм: {len(trigrams)}\n")
    out_f.write(f"(у звіті показано перші {MAX_TRIGRAMS})\n")
    out_f.write("-" * 40 + "\n")
    for (a, b, c), count in trigrams.most_common(MAX_TRIGRAMS):
        out_f.write(f"{format_char(a)} + {format_char(b)} + {format_char(c)}: {count}\n")


def write_skipgram_report(out_f, skipgrams: Counter) -> None:
    out_f.write(f"\nВсього знайдено унікальних skip-грам: {len(skipgrams)}\n")
    out_f.write(f"(у звіті показано перші {MAX_SKIPGRAMS})\n")
    out_f.write("-" * 40 + "\n")
    for (a, b), count in skipgrams.most_common(MAX_SKIPGRAMS):
        out_f.write(f"{format_char(a)} ... {format_char(b)}: {count}\n")


def write_full_report(output_file: str, char_arr, bigram_arr, trigram_arr, skipgram_arr, interrupted: bool):
    char_freqs = array_to_char_counter(char_arr)
    bigrams = array_to_pair_counter(bigram_arr)
    trigrams = array_to_triple_counter(trigram_arr)
    skipgrams = array_to_pair_counter(skipgram_arr)

    with open(output_file, mode='a', encoding='utf-8') as out_f:
        if interrupted:
            out_f.write("\n=== ПЕРЕРВАНО ДОСТРОКОВО ===\n")
        write_char_report(out_f, char_freqs)
        write_bigram_report(out_f, bigrams)
        write_trigram_report(out_f, trigrams)
        write_skipgram_report(out_f, skipgrams)


def write_json_export(json_path: str, char_arr, bigram_arr, trigram_arr, skipgram_arr):
    char_freqs = array_to_char_counter(char_arr)
    bigrams = array_to_pair_counter(bigram_arr)
    trigrams = array_to_triple_counter(trigram_arr)
    skipgrams = array_to_pair_counter(skipgram_arr)

    data = {
        "unigrams": {c: n for c, n in char_freqs.items()},
        "bigrams": {f"{a}{b}": n for (a, b), n in bigrams.items()},
        "trigrams": {f"{a}{b}{c}": n for (a, b, c), n in trigrams.items()},
        "skipgrams": {f"{a}{b}": n for (a, b), n in skipgrams.items()},
    }
    with open(json_path, mode='w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ~~~~~~~~~~~~~~~~~~~~~~~ #
#           main          #
# ~~~~~~~~~~~~~~~~~~~~~~~ #
def main():
    start_time = datetime.now()
    print(f"Старт: {start_time:%Y-%m-%d %H:%M:%S}")

    data_dir = CORPUS_DIR
    if not any(data_dir.glob("ubertext*.txt")):
        raise FileNotFoundError(f"Немає файлів ubertext*.txt у {data_dir}")

    files = sorted(data_dir.glob("ubertext*.txt"))
    output_file = str(PROJ_DIR / ".ignore_result_file.txt")

    print("Нарізаю файли на задачі...")
    tasks = build_tasks(files, TASK_SIZE_BYTES)
    total_bytes = sum(end - start for _, start, end in tasks)
    total_tasks = len(tasks)
    n_workers = max(1, cpu_count() - 1)  # лишаємо одне ядро вільним для системи/інших програм
    print(f"Задач: {total_tasks} (~{TASK_SIZE_MB} МБ кожна), воркерів: {n_workers}\n")

    total_char = np.zeros(ALPHABET_SIZE, dtype=np.int64)
    total_bigram = np.zeros(ALPHABET_SIZE ** 2, dtype=np.int64)
    total_trigram = np.zeros(ALPHABET_SIZE ** 3, dtype=np.int64)
    total_skipgram = np.zeros(ALPHABET_SIZE ** 2, dtype=np.int64)
    bytes_done = 0
    tasks_done = 0

    pool = Pool(processes=n_workers, initializer=init_worker)

    def handle_interrupt(signum, frame):
        print("\nОтримано сигнал зупинки — зберігаю проміжний результат...", flush=True)
        pool.terminate()
        pool.join()
        write_full_report(output_file, total_char, total_bigram, total_trigram, total_skipgram, interrupted=True)
        write_json_export(str(PROJ_DIR / ".ignore_result_file.json"), total_char, total_bigram, total_trigram, total_skipgram)
        elapsed = datetime.now() - start_time
        print(f"Збережено (частково, задачі в польоті на момент сигналу втрачені -- "
              f"до ~{TASK_SIZE_MB} МБ на кожне зайняте ядро). Час до зупинки: {elapsed}", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_interrupt)
    signal.signal(signal.SIGTERM, handle_interrupt)

    try:
        for char_d, bigram_d, trigram_d, skipgram_d, nbytes in pool.imap_unordered(process_task, tasks):
            total_char += char_d
            total_bigram += bigram_d
            total_trigram += trigram_d
            total_skipgram += skipgram_d
            bytes_done += nbytes
            tasks_done += 1
            render_progress(bytes_done, total_bytes, tasks_done, total_tasks)
    finally:
        pool.close()
        pool.join()

    print()  # завершити рядок прогрес-бару

    # filter the result counts
    total_bigram_f = apply_threshold(total_bigram, MIN_NGRAM_COUNT)
    total_trigram_f = apply_threshold(total_trigram, MIN_NGRAM_COUNT)
    total_skipgram_f = apply_threshold(total_skipgram, MIN_NGRAM_COUNT)

    write_full_report(output_file, total_char, total_bigram_f, total_trigram_f, total_skipgram_f, interrupted=False)
    write_json_export(str(PROJ_DIR / "config" / ".ignore_result_file.json"), total_char, total_bigram_f, total_trigram_f, total_skipgram_f)

    end_time = datetime.now()
    elapsed = end_time - start_time
    print(f"Звіт успішно збережено у файл: {output_file}")
    print(f"Фініш: {end_time:%Y-%m-%d %H:%M:%S}")
    print(f"Час виконання: {elapsed}")


if __name__ == "__main__":
    main()
