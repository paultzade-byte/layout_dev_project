"""Точка входу зібраного застосунку (PyInstaller) і зручний запуск GUI.

    python ukr_layout.py            — GUI (те саме, що python -m uiux.app)
    python ukr_layout.py --smoke    — перевірити delta-оцінку (ядра numba), відкрити
                                      вікно і закрити через 3 с (CI)

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


def kernels_selfcheck(steps: int = 30) -> str:
    """Кілька випадкових swap: try_layout (ядра numba, якщо є) == повний score().
    Для --smoke: у зібраному exe numba компілює ядра вперше саме тут."""
    import random
    from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC
    from core import scorer
    from core.layout_factory import build_layout
    layout = build_layout(GEOMETRY_CONFIG)
    engine = scorer.MovementScoringEngine(layout.keys, MOVES_CONFIG).prepare_statistics(STATISTIC)
    engine.load(layout.keys)
    keys = [k for k in layout.keys if k.char and len(k.char) == 1]
    rng = random.Random(1)
    for _ in range(steps):
        a, b = rng.sample(keys, 2)
        a.char, b.char = b.char, a.char
        delta = engine.try_layout(layout.keys)
        full = engine.update_layout(layout.keys).score().total_penalty
        if abs(delta - full) > 1e-9 * abs(full):
            raise RuntimeError(f"delta-оцінка розходиться: {delta} != {full}")
        a.char, b.char = b.char, a.char
    return "numba" if scorer.USE_KERNELS else "numpy"


def run(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    smoke = "--smoke" in argv
    try:
        if smoke:
            print(f"delta selfcheck: OK ({kernels_selfcheck()})", flush=True)
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
