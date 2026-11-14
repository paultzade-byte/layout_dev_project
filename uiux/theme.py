"""Кольори й шрифт — спільні для GUI (uiux/app.py) і картинок (uiux/render.py)."""

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
FONT = "Ubuntu"
KEY_FONT = (FONT, 17, "bold")
