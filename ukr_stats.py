"""Точка входу міні-апки статистики (PyInstaller: ukr-stats.exe поруч з ukr-layout.exe).

    python ukr_stats.py [ТЕКА]   — вікно (те саме, що python -m uiux.stats_app)
    python ukr_stats.py --smoke  — порахувати крихітний корпус воркерами
                                   (перевіряє spawn у зібраному exe), відкрити
                                   вікно і закрити через 3 с (CI)

freeze_support() — обов'язково першим у __main__: воркери підрахунку
(multiprocessing, spawn) у зібраному exe запускають цей самий файл.
"""

import multiprocessing
import sys
import traceback


def smoke_count() -> str:
    import tempfile
    from pathlib import Path
    from core import corpus
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.txt"
        path.write_text("Пʼять м'ясних пиріжків, їжак і ґанок. " * 200, encoding="utf-8")
        result = corpus.count_corpus([path], corpus.detect_language([path]), cpu_share=1.0)
        written = corpus.write_statistic_file(result, tmp, "smoke")
        assert result["statistic"]["unigrams"]["'"] == 400 and written.exists(), "підрахунок неправильний"
    return f"{result['meta']['language']}, {len(result['statistic']['trigrams'])} триграм"


def run(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    smoke = "--smoke" in argv
    try:
        if smoke:
            print(f"corpus selfcheck: OK ({smoke_count()})", flush=True)
        import tkinter as tk
        from uiux.stats_app import StatsApp
        root = tk.Tk()
        StatsApp(root, next((a for a in argv if not a.startswith("--")), None))
        if smoke:
            root.after(3000, root.destroy)
        root.mainloop()
    except Exception:
        text = traceback.format_exc()
        sys.stderr.write(text) if sys.stderr else None
        if not smoke:
            from ukr_layout import _report_crash
            _report_crash(text)
        return 1
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(run())
