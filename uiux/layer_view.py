"""Перегляд шарів клавіатури (лише читання) з дампу studio.py.

Підписи і «як увімкнути» — ті самі, що в схемі шарів для артефакту
(`scripts/zmk/layers_html.py`): кожен шар у своїй мові, у спільних — латиниця,
а кириличний варіант дрібно в кутку, де він інший.
"""

import copy
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
from studio import TAP_PARAM, _norm  # noqa: E402

DUMPS = ROOT / "config" / "zmk"

# кольори шарів — темна палітра артефакту
LAYER_COLORS = {
    "GRAPH": "#7ea2ff", "CYR": "#ff9a6b", "GRAPH_ALT": "#4fd1c0", "CYR_S": "#f6b45a",
    "DIGITS": "#b69cff", "SYMBOL": "#f47fb4", "FN": "#a3acbd", "FN_C": "#8b94a6",
}

KEY = 50
GAP = 6
# дошка 860 px (вікно 900 − відступи 2×20), блок клавіш 786 px — по центру
BASE_X, BASE_Y = 37, 22
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
    return _norm(json.loads(Path(path).read_text(encoding="utf-8")))


READ_ONLY = {"CYR"}  # кирилиця редагується в «Редакторі» (там же штраф)
CHANGED = "#ffffff"  # рамка клавіші, зміненої, але ще не записаної


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
    який вмикає утримання; ▽ — прозора, порожня — без підпису.

    Редагування (усі шари, крім READ_ONLY): перетягнути клавішу на іншу —
    обмін тапами, утримання лишаються на позиціях (як у редакторі CYR);
    Shift+перетягування — обмін клавішами цілком. ПКМ — повернути клавішу,
    як на клавіатурі. Зміни живуть у self.dump (робоча копія) до запису;
    self.base — стан клавіатури, з яким порівнюємо."""

    def __init__(self, parent, colors, on_change=None):
        """colors: PANEL, SLOT, TEXT_DIM, KEY_TEXT, FONT, FINGER {pinky/ring/middle/index/thumb: колір}."""
        self.c = colors
        self.on_change = on_change or (lambda: None)
        super().__init__(parent, bg=colors["PANEL"], bd=0)
        # один Canvas, елементи створюються раз — show() лише міняє текст/кольори
        self.canvas = tk.Canvas(self, bg=colors["PANEL"], highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        # підпис — під клавішами (над ними місця на 1 рядок, а активаторів буває 5–7)
        self.caption = tk.Label(self, bg=colors["PANEL"], fg=colors["TEXT_DIM"], anchor="nw",
                                justify="left", font=(colors["FONT"], 9), wraplength=780)
        self.caption.place(x=BASE_X, y=BASE_Y + 4 * (KEY + GAP) + 2, relwidth=1.0, width=-2 * BASE_X)
        self.items = {pos: self._make_key(pos, *xy(*cell)) for pos, cell in CELLS.items()}
        self.ghost = None
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._drag_release)
        self.canvas.bind("<Button-3>", self._revert_at)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Leave>", lambda e: self.caption_hint(None))
        self._hover_pos = None
        self.about = ""
        self.dump = None      # робоча копія (з незаписаними змінами)
        self.base = None      # як на клавіатурі
        self.source = ""
        self.layer_name = None
        self._drag = None

    def _make_key(self, pos, x, y):
        cv, f = self.canvas, self.c["FONT"]
        return {
            "box": cv.create_polygon(rounded(x, y, x + KEY, y + KEY, 7), smooth=True, width=2, outline=""),
            "top": cv.create_line(x + 6, y + 2, x + KEY - 6, y + 2, width=3, fill="", capstyle="round"),
            "bot": cv.create_line(x + 6, y + KEY - 3, x + KEY - 6, y + KEY - 3, width=4, fill="", capstyle="round"),
            # тап завжди на одній висоті (з утриманням чи без) — не скаче
            "tap": cv.create_text(x + KEY / 2, y + 20, text="", font=(f, 17, "bold")),
            "hold": cv.create_text(x + KEY / 2, y + 38, text="", font=(f, 7)),
            "alt": cv.create_text(x + KEY - 4, y + 3, text="", anchor="ne", font=(f, 8, "bold"), fill="#b4380c"),
        }

    # --- стан ------------------------------------------------------------
    def set_dump(self, dump, source):
        """Новий стан клавіатури; незаписані зміни відкидаються."""
        self.base = copy.deepcopy(dump)
        self.dump = copy.deepcopy(dump)
        self.source = source
        self.on_change()

    def sync_layer(self, name, bindings):
        """Шар щойно записали іншим шляхом (CYR з редактора) — оновити його в обох копіях."""
        for d in (self.base, self.dump):
            if d is not None:
                self._layer(name, d)["bindings"] = copy.deepcopy(bindings)

    @staticmethod
    def _layer(name, dump):
        return next((l for l in dump["layers"] if l["name"] == name), None)

    def pending(self):
        """-> {шар: [позиції]} змінених, ще не записаних клавіш."""
        out = {}
        if self.dump is None:
            return out
        for layer in self.dump["layers"]:
            old = self._layer(layer["name"], self.base)["bindings"]
            diff = [i for i, (a, b) in enumerate(zip(old, layer["bindings"])) if a != b]
            if diff:
                out[layer["name"]] = diff
        return out

    def editable(self, name=None):
        return (name or self.layer_name) not in READ_ONLY and self.dump is not None

    def _tap_index(self, binding):
        return TAP_PARAM.get(self.dump["behaviors"].get(binding[0]))

    def swap(self, a, b, whole=False):
        bb = self._layer(self.layer_name, self.dump)["bindings"]
        ia, ib = self._tap_index(bb[a]), self._tap_index(bb[b])
        if whole or ia is None or ib is None:
            bb[a], bb[b] = bb[b], bb[a]
        else:
            bb[a] = list(bb[a]); bb[b] = list(bb[b])
            bb[a][ia], bb[b][ib] = bb[b][ib], bb[a][ia]
        self._changed()

    def revert(self, pos):
        cur = self._layer(self.layer_name, self.dump)["bindings"]
        cur[pos] = copy.deepcopy(self._layer(self.layer_name, self.base)["bindings"][pos])
        self._changed()

    def reset_layer(self, name=None):
        name = name or self.layer_name
        self._layer(name, self.dump)["bindings"] = copy.deepcopy(self._layer(name, self.base)["bindings"])
        self._changed()

    def _changed(self):
        self.show(self.layer_name)
        self.on_change()

    # --- малювання -------------------------------------------------------
    def show(self, layer_name):
        self.layer_name = layer_name
        if self.dump is None:
            self.caption.config(text="Немає дампу клавіатури — натисни «З клави» або ⟳.")
            return
        dl.use(self.dump)
        layer = self._layer(layer_name, self.dump)
        if layer is None:
            self.caption.config(text=f"У дампі немає шару {layer_name}.")
            return
        how = ("перетягни — обмін тапами (утримання лишаються), Shift+перетягни — клавішами цілком, "
               "ПКМ — повернути" if self.editable(layer_name) else "лише перегляд — кирилиця редагується в «Редакторі»")
        self.about = (f"{lh.ABOUT.get(layer_name, '')}  ({how})\n"
                      f"Як увімкнути: {merged_activators(layer_name, self.dump)}")
        self.caption_hint(None)
        changed = set(self.pending().get(layer_name, []))
        self.canvas.config(cursor="hand2" if self.editable(layer_name) else "")
        for pos in CELLS:
            self._draw_key(pos, layer["bindings"][pos], layer_name, pos in changed)

    def _draw_key(self, pos, binding, layer_name, changed):
        c, cv, it = self.c, self.canvas, self.items[pos]
        lang = lh.LANG.get(layer_name)
        k = lh.key(binding, lang or "us")
        alt = ""
        if lang is None and k["kind"] in ("key", "ht", "lt"):
            ua = lh.key(binding, "ua")
            if ua["tap"] != k["tap"]:
                alt = ua["tap"]
        empty = k["kind"] in ("none", "trans")
        bg = c["SLOT"] if empty else c["FINGER"][finger_of(pos)]
        fg = c["TEXT_DIM"] if empty else c["KEY_TEXT"]
        tap = "▽" if k["kind"] == "trans" else k["tap"]
        size = 17 if len(tap) <= 2 else 12 if len(tap) <= 4 else 8
        layer_color = LAYER_COLORS.get(k.get("layer"), c["TEXT_DIM"])
        cv.itemconfig(it["box"], fill=bg, outline=CHANGED if changed else "")
        cv.itemconfig(it["tap"], text=tap, fill=fg, font=(c["FONT"], size, "bold"))
        cv.itemconfig(it["hold"], text=k.get("hold") or "", fill=fg)
        cv.itemconfig(it["alt"], text=alt)
        cv.itemconfig(it["bot"], fill=layer_color if k["kind"] == "lt" and k.get("layer") else "")
        cv.itemconfig(it["top"], fill=layer_color if k["kind"] in ("to", "lang") else "")
        it["tap_text"] = tap

    # --- миша ------------------------------------------------------------
    def _pos_at(self, x, y):
        """Позиція клавіші під точкою (координати Canvas) — за геометрією."""
        for pos, cell in CELLS.items():
            kx, ky = xy(*cell)
            if kx <= x < kx + KEY + GAP and ky <= y < ky + KEY + GAP:
                return pos
        return None

    def _hover(self, event):
        pos = self._pos_at(event.x, event.y)
        if pos != self._hover_pos:
            self._hover_pos = pos
            self.caption_hint(lh.pos_name(pos) if pos is not None else None)
        if self._drag:
            self._drag_motion(event)

    def _drag_start(self, event):
        pos = self._pos_at(event.x, event.y)
        if pos is None or not self.editable():
            return
        tap = self.items[pos].get("tap_text") or "·"
        self.ghost = self.canvas.create_text(event.x + 14, event.y + 14, text=tap, anchor="nw",
                                             font=(self.c["FONT"], 14, "bold"), fill=CHANGED)
        self._drag = pos

    def _drag_motion(self, event):
        if self._drag is not None and self.ghost:
            self.canvas.coords(self.ghost, event.x + 14, event.y + 14)

    def _drag_release(self, event):
        src, self._drag = self._drag, None
        if self.ghost:
            self.canvas.delete(self.ghost)
            self.ghost = None
        if src is None:
            return
        target = self._pos_at(event.x, event.y)
        if target is not None and target != src:
            self.swap(src, target, whole=bool(event.state & 0x0001))  # Shift

    def _revert_at(self, event):
        pos = self._pos_at(event.x, event.y)
        if pos is not None and self.editable():
            self.revert(pos)

    def caption_hint(self, text):
        self.caption.config(text=f"{self.about}\n{text or f'джерело: {self.source}'}")


def rounded(x1, y1, x2, y2, r):
    """Точки для create_polygon(smooth=True) — прямокутник із заокругленими кутами."""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
