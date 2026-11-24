"""Кольори й шрифт — спільні для GUI (uiux/app.py) і картинок (uiux/render.py)."""

import sys

from core.models import Finger

BG = "#16181d"            # вікно
PANEL = "#1f2229"         # дошка
SLOT = "#2a2e37"          # порожній слот
TEXT = "#e6e8ee"
TEXT_DIM = "#8b91a0"
ACCENT = "#7aa2f7"
BUTTON = "#2c313c"
BUTTON_HOVER = "#3a4050"
KEY_TEXT = "#16181d"
FROZEN_BG = "#2c313c"     # заморожена клавіша: темна з бурштиновою рамкою
FROZEN_FG = "#f6c177"
DROP_OK = "#ffffff"       # підсвітка цілі при перетягуванні
DROP_BLOCKED = "#eb6f92"
# зони пальців — однакові для обох рук
FINGER_COLORS = {
    Finger.PINKY: "#c4a7e7",
    Finger.RING: "#9ccfd8",
    Finger.MIDDLE: "#f6c177",
    Finger.INDEX: "#a6da95",
    Finger.THUMB: "#8b91a0",
}
# шрифт інтерфейсу: на кожній ОС — штатний (Ubuntu на Windows/macOS немає,
# і Tk підставив би випадковий)
FONT = {"win32": "Segoe UI", "darwin": "Helvetica Neue"}.get(sys.platform, "Ubuntu")
KEY_FONT = (FONT, 17, "bold")


def set_window_icon(root, name: str) -> None:
    """Іконка вікна Tk (заголовок, панель задач): packaging/icons/<name>.png;
    у зібраному exe — <_MEIPASS>/icons. Немає файлу чи Tk не зміг — без іконки."""
    import tkinter as tk
    from config.paths import PROJ_DIR
    for path in (PROJ_DIR / "icons" / f"{name}.png", PROJ_DIR / "packaging" / "icons" / f"{name}.png"):
        if path.exists():
            try:
                root._icon_image = tk.PhotoImage(file=str(path))  # посилання, щоб GC не з'їв
                root.iconphoto(True, root._icon_image)
            except tk.TclError:
                pass
            return
