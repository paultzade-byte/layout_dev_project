"""Вікно «Тренування»: модальне, поверх головного, з розкладкою з дошки.

    TrainerWindow(root, keys, geometry, geometry_name, statistic)

Логіка (тексти, рівні, перекладач) — core/trainer.py. Частина 1: режим «Слова»;
«Поєднання» (біграми/триграми) і «Класика» (цитати цілком) — далі.
Налаштування (переклад, рівень на кожну геометрію) — settings.json.
"""

from __future__ import annotations

import random
import time
import tkinter as tk

from config import settings
from core import trainer
from uiux import tooltip
from uiux.render import key_cells
from uiux.theme import (ACCENT, BG, BUTTON, BUTTON_HOVER, DROP_BLOCKED, FINGER_COLORS, FONT, KEY_TEXT,
                        PANEL, SLOT, TEXT, TEXT_DIM)
from uiux.widgets import RoundButton

BOARD_SCALE = 0.55
MODES = (("words", "Слова", "Слова з цитат української класики (поки мало літер — і псевдослова "
                            "з них). Слова з новою літерою трапляються частіше."),
         ("ngrams", "Поєднання", "Скоро: вправи на найважчі для цієї розкладки пари й трійки літер."),
         ("quotes", "Класика", "Скоро: цілі цитати Франка, Лесі Українки, Коцюбинського, Стефаника…"))


def _button(parent, text, command, small=True):
    return RoundButton(parent, text=text, command=command, font=(FONT, 9 if small else 11, "bold"),
                       bg=BUTTON, fg=TEXT, activebackground=BUTTON_HOVER, disabledforeground=TEXT_DIM,
                       padx=8 if small else 14, pady=3 if small else 5, radius=6)


class TrainerWindow:
    def __init__(self, root: tk.Misc, keys, geometry: dict, geometry_name: str, statistic: dict):
        self.geometry, self.geometry_name = geometry, geometry_name
        self.chars = {k.position_id: k.char for k in keys}
        self.rng = random.Random()
        self.source = trainer.WordSource(trainer.quote_words(trainer.load_quotes()),
                                         statistic.get("bigrams", {}), self.rng)
        self.order = trainer.make_order(self.chars, geometry, statistic.get("unigrams", {}))
        self.levels = trainer.level_count(self.order)
        saved = settings.load()
        self.can_translate = trainer.can_translate(geometry)
        self.translate = self.can_translate and saved.get("trainer_translate", True)
        self.level = min(saved.get("trainer_levels", {}).get(geometry_name, 0), self.levels - 1)
        self.mode = "words"
        self.done_lines = []        # (cpm, accuracy) завершених рядків цієї сесії

        self.win = tk.Toplevel(root)
        self.win.title("Тренування")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(root)
        self._build()
        self.translator = trainer.Translator(self.chars, geometry, self.win.tk.call("tk", "windowingsystem"))
        self.win.bind("<KeyPress>", self._on_key)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._new_line()
        self._center(root)
        self.win.wait_visibility()
        self.win.grab_set()                   # модальне: головне вікно чекає
        self.win.focus_force()

    # ------------------------------------------------------------------
    def _build(self):
        w = self.win
        top = tk.Frame(w, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        self.mode_buttons = {}
        for mode, title, tip in MODES:
            b = _button(top, title, lambda m=mode: self._set_mode(m))
            b.pack(side="left", padx=(0, 6))
            if mode != "words":
                b.config(state="disabled")
            tooltip.add(b, tip)
            self.mode_buttons[mode] = b

        self.button_translate = _button(top, "", self._toggle_translate)
        self.button_translate.pack(side="right")
        tooltip.add(self.button_translate, self._translate_tip)

        lv = tk.Frame(w, bg=BG)
        lv.pack(fill="x", padx=16, pady=(4, 4))
        tk.Label(lv, text="Літери", bg=BG, fg=TEXT_DIM, font=(FONT, 10)).pack(side="left")
        self.scale = tk.Scale(lv, from_=0, to=self.levels - 1, orient="horizontal", showvalue=False,
                              length=220, bg=BG, fg=TEXT, troughcolor=PANEL, highlightthickness=0,
                              bd=0, sliderlength=18, command=self._on_level)
        self.scale.set(self.level)
        self.scale.pack(side="left", padx=8)
        self.letters_label = tk.Label(lv, bg=BG, fg=TEXT, font=(FONT, 10))
        self.letters_label.pack(side="left")
        tip = ("Складність: скільки літер у вправах. Ліворуч — лише домашній ряд, "
               f"кожен крок праворуч додає {trainer.STEP} літери (за частотою), до кінця — усі.\n"
               "Нова літера підсвічена — на ній варто зосередитись.")
        tooltip.add(self.scale, tip)
        tooltip.add(self.letters_label, tip)

        self.text = tk.Text(w, height=2, width=46, wrap="word", bg=PANEL, fg=TEXT_DIM, bd=0,
                            font=(FONT, 20), padx=14, pady=12, highlightthickness=0, cursor="arrow",
                            spacing2=6)
        self.text.pack(padx=16, pady=(6, 8))
        self.text.tag_configure("done", foreground=TEXT)
        self.text.tag_configure("wrong", foreground=DROP_BLOCKED)
        self.text.tag_configure("cursor", background=ACCENT, foreground=KEY_TEXT)
        self.text.tag_configure("cursor_wrong", background=DROP_BLOCKED, foreground=KEY_TEXT)
        self.text.bind("<Button-1>", lambda e: "break")
        tooltip.add(self.text, "Друкуй підсвічену літеру. Помилка — літера червоніє, курсор чекає "
                               "правильну. Рядок закінчився — одразу наступний.")

        cells = key_cells(self.geometry, self.geometry_name)
        s = BOARD_SCALE
        width = max(x + cw for _, x, _, cw in cells) * s
        height = max(y for _, _, y, _ in cells) * s + self.geometry["key_height"] * s
        self.board = tk.Canvas(w, width=width + 4, height=height + 4, bg=BG, highlightthickness=0)
        self.board.pack(padx=16, pady=(0, 8))
        self.board_keys = {}
        for pos, x, y, cw in cells:
            ch = self.chars.get(pos["id"], "")
            x0, y0 = x * s + 2, y * s + 2
            x1, y1 = x0 + cw * s, y0 + self.geometry["key_height"] * s
            rect = self.board.create_rectangle(x0, y0, x1, y1, outline="", width=0)
            label = ch if ch in trainer.ALPHABET else ""
            self.board.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=label, fill=KEY_TEXT,
                                   font=(FONT, 11, "bold"))
            alt = self.geometry.get("altgr", {}).get(ch, "")
            if alt:
                self.board.create_text(x1 - 6, y0 + 8, text=alt, fill=KEY_TEXT, font=(FONT, 7))
            self.board_keys[pos["id"]] = (rect, ch, pos.get("finger", ""))
        tooltip.add(self.board, "Розкладка з дошки головного вікна. Синім — клавіша, яку натиснути "
                                "зараз; сірі — літери, яких ще нема у вправах.")

        bottom = tk.Frame(w, bg=BG)
        bottom.pack(fill="x", padx=16, pady=(0, 14))
        self.stats_label = tk.Label(bottom, bg=BG, fg=TEXT, font=(FONT, 10), anchor="w", justify="left")
        self.stats_label.pack(side="left")
        tooltip.add(self.stats_label, "Швидкість — правильних знаків за хвилину (зн/хв). Точність — "
                                      "частка натискань без помилки. «Сесія» — середнє за всі "
                                      "завершені рядки, відколи відкрито вікно.")
        close = _button(bottom, "Закрити", self.close, small=False)
        close.pack(side="right")
        tooltip.add(close, "Закрити тренування (Esc). Рівень і переклад запам'ятовуються.")
        again = _button(bottom, "Інший рядок", self._new_line, small=False)
        again.pack(side="right", padx=(0, 8))
        tooltip.add(again, "Пропустити цей рядок і взяти новий.")
        self._update_translate_button()

    # ------------------------------------------------------------------
    def _translate_tip(self):
        if not self.can_translate:
            return ("Corne сама надсилає літери з прошивки — друкуй як є. Перекладач фізичних клавіш "
                    "є для звичайної клавіатури.")
        return ("Перекладати: у системі стоїть звичайна розкладка (ЙЦУКЕН чи англійська), а тренажер "
                "бере літеру з цієї розкладки за фізичною клавішею — можна вчитись, не встановлюючи її. "
                "AltGr (правий Alt) — другий символ клавіші.\n"
                "Як є: розкладку вже встановлено в систему — літери беруться такі, як надсилає система.")

    def _update_translate_button(self):
        text = "Клавіші: перекладати" if self.translate else "Клавіші: як є"
        self.button_translate.config(text=text, state="normal" if self.can_translate else "disabled")

    def _toggle_translate(self):
        self.translate = not self.translate
        settings.save(trainer_translate=self.translate)
        self._update_translate_button()

    def _set_mode(self, mode):
        self.mode = mode
        self._new_line()

    def _on_level(self, value):
        level = int(float(value))
        if level == self.level and hasattr(self, "session"):
            return
        self.level = level
        levels = {**settings.load().get("trainer_levels", {}), self.geometry_name: level}
        settings.save(trainer_levels=levels)
        if hasattr(self, "session"):
            self._new_line()

    # ------------------------------------------------------------------
    def _new_line(self):
        self.allowed = trainer.letters_at(self.order, self.level)
        self.focus = self.allowed[-1] if self.level > 0 else None
        self.session = trainer.Session(self.source.line(self.allowed, self.focus))
        n, total = len(self.allowed), len(self.order)
        focus = f" · нова: «{self.focus}»" if self.focus else " · домашній ряд"
        self.letters_label.config(text=f"{n} з {total}{focus}")
        self._paint_board()
        self._render()
        self._show_stats()

    def _paint_board(self):
        nxt = self.session.text[self.session.pos] if not self.session.done else ""
        altgr = self.geometry.get("altgr", {})
        for pid, (rect, ch, finger) in self.board_keys.items():
            if ch in trainer.ALPHABET:
                on = ch in self.allowed
                base = FINGER_COLORS.get(_finger(finger), SLOT) if on else SLOT
                if nxt and (ch == nxt or altgr.get(ch) == nxt):
                    base = ACCENT
                if self.focus and ch == self.focus and ch != nxt:
                    self.board.itemconfigure(rect, fill=base, outline=ACCENT, width=2)
                    continue
                self.board.itemconfigure(rect, fill=base, outline="", width=0)
            else:
                self.board.itemconfigure(rect, fill=PANEL, outline="", width=0)

    def _render(self):
        s = self.session
        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", s.text)
        for tag in ("done", "wrong", "cursor", "cursor_wrong"):
            t.tag_remove(tag, "1.0", "end")
        if s.pos:
            t.tag_add("done", "1.0", f"1.{s.pos}")
        for i in s.wrong_at:
            if i < s.pos:
                t.tag_add("wrong", f"1.{i}", f"1.{i + 1}")
        if not s.done:
            t.tag_add("cursor_wrong" if s.pos in s.wrong_at else "cursor", f"1.{s.pos}", f"1.{s.pos + 1}")
            t.see(f"1.{s.pos}")
        t.config(state="disabled")

    def _show_stats(self):
        s = self.session
        now = time.monotonic()
        line = f"Швидкість: {s.cpm(now):.0f} зн/хв · Точність: {s.accuracy():.0f}%"
        if self.done_lines:
            cpm = sum(c for c, _ in self.done_lines) / len(self.done_lines)
            acc = sum(a for _, a in self.done_lines) / len(self.done_lines)
            line += f"\nСесія ({len(self.done_lines)} ряд.): {cpm:.0f} зн/хв · {acc:.0f}%"
        self.stats_label.config(text=line)

    # ------------------------------------------------------------------
    def _on_key(self, event):
        if event.keysym == "Escape":
            return
        if self.translate:
            ch = self.translator.translate(event.keycode, event.char, event.state)
        else:
            ch = trainer.as_is(event.char)
        if ch is None:
            return "break"
        s = self.session
        s.type(ch, time.monotonic())
        if s.done:
            self.done_lines.append((s.cpm(time.monotonic()), s.accuracy()))
            self._new_line()
            return "break"
        self._paint_board()
        self._render()
        self._show_stats()
        return "break"

    def _center(self, root):
        self.win.update_idletasks()
        top = root.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.win.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + max(0, (top.winfo_height() - self.win.winfo_reqheight()) // 3)
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def close(self):
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()


def _finger(name: str):
    """'L_index' -> Finger.INDEX (кольори пальців з теми)."""
    from core.models import Finger
    part = name.split("_", 1)[-1].upper()
    return getattr(Finger, part, None)
