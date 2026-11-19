"""Точка входу зібраного застосунку (PyInstaller) і зручний запуск GUI.

    python ukr_layout.py            — GUI (те саме, що python -m uiux.app)
    python ukr_layout.py --smoke    — відкрити вікно і закрити через 3 с (CI)

У віконному exe немає консолі, тож необроблена помилка інакше зникла б
безслідно: її текст пишеться в user_data_dir()/error.log і показується
у вікні повідомлення.
"""

import sys
import traceback


def _report_crash(text: str) -> None:
    try:
        from config.paths import user_data_dir
        log = user_data_dir() / "error.log"
        log.write_text(text, encoding="utf-8")
        where = f"\n\nПовний текст: {log}"
    except Exception:
        where = ""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Аналізатор розкладки — помилка",
                             text.strip().splitlines()[-1] + where)
        root.destroy()
    except Exception:
        pass


def run(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    smoke = "--smoke" in argv
    try:
        from uiux.app import main
        main(smoke_ms=3000 if smoke else None)
    except Exception:
        text = traceback.format_exc()
        sys.stderr.write(text) if sys.stderr else None
        if not smoke:
            _report_crash(text)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
