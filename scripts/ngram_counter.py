"""Статистика корпусу -> statistic.json + word_stats.json (CLI до core/corpus.py).

Те саме, що міні-апка `python -m uiux.stats_app`, але з командного рядка:

    python scripts/ngram_counter.py ТЕКА_АБО_ФАЙЛИ... [--lang auto|uk|be|pl]
                                    [--out ТЕКА] [--cpu 25]

Читаються всі .txt (з підтеками). Мова за замовчуванням визначається сама.
--out — куди записати statistic.json і word_stats.json (типово — поточна
тека; для оптимізатора в репо — `--out config`). --cpu — % усієї машини.
Раніше тут був окремий лічильник n-грам, а слова рахував
scripts/word_counter.py — тепер обидва в одному проході (core/corpus.py).
Корпус автора — `.ignore_storage/dirty_data` (UberText, ~16 ГБ).
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import corpus  # noqa: E402


def main(argv=None):
    # Windows-консоль/пайп типово cp1252 -> кирилиця в повідомленнях падала б UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="теки з .txt (з підтеками) або .txt-файли")
    ap.add_argument("--lang", default="auto", choices=["auto", *corpus.LANGUAGES])
    ap.add_argument("--out", default=".", help="тека для statistic.json і word_stats.json")
    ap.add_argument("--cpu", type=float, default=25, help="%% усієї машини (типово 25)")
    args = ap.parse_args(argv)

    files = corpus.find_corpus_files(args.paths)
    if not files:
        sys.exit("немає файлів .txt")
    try:
        corpus.check_utf8(files)
    except ValueError as e:
        sys.exit(f"помилка: {e}")
    lang = corpus.detect_language(files) if args.lang == "auto" else args.lang
    if lang is None:
        sys.exit("мову не визначено — вкажіть --lang")
    # тека --out без права на запис — до підрахунку, а не traceback після годин роботи;
    # після перевірок вводу, щоб не лишати теку, коли скрипт одразу виходить
    try:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        tempfile.TemporaryFile(dir=args.out).close()
    except OSError as e:
        sys.exit(f"помилка: у теку --out {args.out} не записати: {e}")
    workers, duty = corpus.worker_plan(args.cpu / 100)
    print(f"{len(files)} файлів, мова {lang}, воркерів {workers} по {duty:.0%}", flush=True)

    def progress(p):
        bar = "#" * int(40 * p.fraction)
        print(f"\r  [{bar:<40}] {p.fraction:6.1%}  задач {p.tasks_done}/{p.tasks_total}  "
              f"{p.elapsed / 60:.1f} хв", end="", flush=True)

    t0 = time.perf_counter()
    try:
        result = corpus.count_corpus(files, lang, args.cpu / 100, progress)
    except ValueError as e:
        print()
        sys.exit(f"помилка: {e}")
    print()
    try:
        paths = corpus.write_outputs(result, args.out)
    except OSError as e:
        sys.exit(f"помилка: не вдалося записати статистику в {args.out}: {e}")
    for path in paths:
        print("записано", path)
    print(result["meta"], f"\nчас {(time.perf_counter() - t0) / 60:.1f} хв")


if __name__ == "__main__":
    main()
