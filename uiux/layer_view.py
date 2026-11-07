"""Перегляд шарів клавіатури (лише читання) з дампу studio.py.

Підписи і «як увімкнути» — ті самі, що в схемі шарів для артефакту
(`scripts/zmk/layers_html.py`): кожен шар у своїй мові, у спільних — латиниця,
а кириличний варіант дрібно в кутку, де він інший.
"""

import json
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZMK_SCRIPTS = ROOT / "scripts" / "zmk"
if str(ZMK_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ZMK_SCRIPTS))

import draw_layers as dl  # noqa: E402
import layers_html as lh  # noqa: E402

DUMPS = ROOT / "config" / "zmk"

# кольори шарів — темна палітра артефакту
LAYER_COLORS = {
    "GRAPH": "#7ea2ff", "CYR": "#ff9a6b", "GRAPH_ALT": "#4fd1c0", "CYR_S": "#f6b45a",
    "DIGITS": "#b69cff", "SYMBOL": "#f47fb4", "FN": "#a3acbd", "FN_C": "#8b94a6",
}

KEY = 50
GAP = 6
BASE_X, BASE_Y = 50, 40
RIGHT_SHIFT = 400  # як у LayoutBuilderApp.build_grid для corne_42


def eyelash_cells():
    """позиція Eyelash -> (row, col, hand) у координатах дошки редактора."""
    cells = {}
    for r, row in enumerate(lh.ROWS):
        for c, pos in enumerate(row):
            if pos is None:
                continue
            cells[pos] = (r, c, "L") if c < 6 else (r, c - 6, "R")
    for i, pos in enumerate((42, 43, 44)):
        cells[pos] = (3, 3 + i, "L")
    for i, pos in enumerate((45, 46, 47)):
        cells[pos] = (3, 1 + i, "R")
    return cells


CELLS = eyelash_cells()
# палець за колонкою (ліва 0..5, права 1..6 — як у geometry.json)
_FINGER_L = ["pinky", "pinky", "ring", "middle", "index", "index"]
_FINGER_R = [None, "index", "index", "middle", "ring", "pinky", "pinky"]


def finger_of(pos):
    row, col, hand = CELLS[pos]
    if row == 3:
        return "thumb"
    return _FINGER_L[col] if hand == "L" else _FINGER_R[col]


def xy(row, col, hand):
    x = BASE_X + col * (KEY + GAP) + (RIGHT_SHIFT if hand == "R" else 0)
    return x, BASE_Y + row * (KEY + GAP)


def latest_dump():
    """Найсвіжіший дамп у config/zmk (за часом зміни) або None."""
    files = sorted(DUMPS.glob("studio_keymap_*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def load_dump(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def merged_activators(layer_name, dump):
    """«утримання: X на GRAPH», «… на CYR» -> «утримання: X на GRAPH, CYR»."""
    dl.use(dump)
    groups = {}
    for a in lh.activators(layer_name, dump):
        head, sep, src = a.rpartition(" на ")
        if not sep:
            head, src = a, ""
        groups.setdefault(head, []).append(src)
    parts = [f"{h} на {', '.join(s for s in srcs if s)}" if any(srcs) else h for h, srcs in groups.items()]
    return "; ".join(parts) or "базовий шар"


class LayerView(tk.Frame):
    """Дошка шару: тап великим, утримання дрібно знизу, смужка кольору шару,
    який вмикає утримання; ▽ — прозора, порожня — без підпису."""

    def __init__(self, parent, colors):
        """colors: PANEL, SLOT, TEXT_DIM, KEY_TEXT, FONT, FINGER {pinky/ring/middle/index/thumb: колір}."""
        self.c = colors
        super().__init__(parent, bg=colors["PANEL"], bd=0)
        # підпис — під клавішами (над ними місця на 1 рядок, а активаторів буває 5–7)
        self.caption = tk.Label(self, bg=colors["PANEL"], fg=colors["TEXT_DIM"], anchor="nw",
                                justify="left", font=(colors["FONT"], 9), wraplength=760)
        self.caption.place(x=BASE_X, y=BASE_Y + 4 * (KEY + GAP) - 4, relwidth=1.0, width=-2 * BASE_X)
        self.widgets = []
        self.about = ""
        self.dump = None
        self.source = ""

    def set_dump(self, dump, source):
        self.dump = dump
        self.source = source

    def show(self, layer_name):
        for w in self.widgets:
            w.destroy()
        self.widgets.clear()
        if self.dump is None:
            self.caption.config(text="Немає дампу клавіатури — натисни «З клави» або ⟳.")
            return
        dl.use(self.dump)
        layer = next((l for l in self.dump["layers"] if l["name"] == layer_name), None)
        if layer is None:
            self.caption.config(text=f"У дампі немає шару {layer_name}.")
            return
        self.about = f"{lh.ABOUT.get(layer_name, '')}\nЯк увімкнути: {merged_activators(layer_name, self.dump)}"
        self.caption.config(text=f"{self.about}\nджерело: {self.source}")
        for pos, (row, col, hand) in CELLS.items():
            self._key(pos, layer["bindings"][pos], layer_name, *xy(row, col, hand))

    def _key(self, pos, binding, layer_name, x, y):
        c = self.c
        lang = lh.LANG.get(layer_name)
        k = lh.key(binding, lang or "us")
        alt = None
        if lang is None and k["kind"] in ("key", "ht", "lt"):
            ua = lh.key(binding, "ua")
            if ua["tap"] != k["tap"]:
                alt = ua["tap"]

        if k["kind"] == "none":
            bg, fg = c["SLOT"], c["TEXT_DIM"]
        elif k["kind"] == "trans":
            bg, fg = c["SLOT"], c["TEXT_DIM"]
        else:
            bg, fg = c["FINGER"][finger_of(pos)], c["KEY_TEXT"]
        box = tk.Frame(self, bg=bg, width=KEY, height=KEY)
        box.place(x=x, y=y)
        self.widgets.append(box)
        tip = lh.pos_name(pos)

        tap = "▽" if k["kind"] == "trans" else k["tap"]
        if k["kind"] in ("to", "lang"):
            fg = LAYER_COLORS.get(k.get("layer"), c["KEY_TEXT"]) if bg == c["SLOT"] else c["KEY_TEXT"]
        size = 17 if len(tap) <= 2 else 12 if len(tap) <= 4 else 8
        has_hold = bool(k.get("hold"))
        tk.Label(box, text=tap, bg=bg, fg=fg, font=(c["FONT"], size, "bold")).place(
            relx=0.5, rely=0.38 if has_hold else 0.5, anchor="center")
        if has_hold:
            tk.Label(box, text=k["hold"], bg=bg, fg=fg, font=(c["FONT"], 7)).place(
                relx=0.5, rely=0.78, anchor="center")
        if alt:
            tk.Label(box, text=alt, bg=bg, fg="#b4380c", font=(c["FONT"], 8, "bold")).place(
                relx=1.0, x=-2, y=0, anchor="ne")
        if k.get("layer") and k["kind"] == "lt":
            tk.Frame(box, bg=LAYER_COLORS.get(k["layer"], c["TEXT_DIM"]), height=4).place(
                x=0, rely=1.0, y=-4, relwidth=1.0)
        if k["kind"] in ("to", "lang"):
            tk.Frame(box, bg=LAYER_COLORS.get(k.get("layer"), c["TEXT_DIM"]), height=3).place(
                x=0, y=0, relwidth=1.0)
        for w in [box] + box.winfo_children():
            w.bind("<Enter>", lambda e, t=tip: self.caption_hint(t))
            w.bind("<Leave>", lambda e: self.caption_hint(None))

    def caption_hint(self, text):
        self.caption.config(text=f"{self.about}\n{text or f'джерело: {self.source}'}")
