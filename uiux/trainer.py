"""Вікно «Тренування»: модальне, поверх головного, з розкладкою з дошки.

    TrainerWindow(root, keys, geometry, geometry_name, statistic, hard_ngrams)

Логіка (тексти, рівні, перекладач, статистика) — core/trainer.py. Режими «Слова» і
«Поєднання» (hard_ngrams — найдорожчі для розкладки бі/триграми з engine головного
вікна); «Класика» (цитати цілком) — частина 3.
Налаштування (переклад, режим, «Сам підвищуй», рівень на кожну геометрію) — settings.json;
статистика по літерах — trainer_stats.json поруч.
"""

from __future__ import annotations

import random
import time
import tkinter as tk
from tkinter import messagebox

from config import settings
from core import trainer
from uiux import tooltip
from uiux.render import key_cells
from uiux.toast import Toasts
from uiux.theme import (ACCENT, BG, BUTTON, BUTTON_HOVER, DROP_BLOCKED, FINGER_COLORS, FONT, KEY_TEXT,
                        PANEL, SLOT, TEXT, TEXT_DIM)
from uiux.widgets import RoundButton

BOARD_SCALE = 0.55
MODES = (("words", "Слова", "Слова з цитат української класики (поки мало літер — і псевдослова "
                            "з них). Слова з новою літерою трапляються частіше."),
         ("ngrams", "Поєднання", "Найважчі для цієї розкладки пари й трійки літер (ті, що найбільше "
                                 "додають до штрафу): по кілька слів поспіль на кожне поєднання. "
                                 "Лише з відкритих літер."),
         ("quotes", "Класика", "Скоро: цілі цитати Франка, Лесі Українки, Коцюбинського, Стефаника…"))


def _button(parent, text, command, small=True):
    return RoundButton(parent, text=text, command=command, font=(FONT, 9 if small else 11, "bold"),
                       bg=BUTTON, fg=TEXT, activebackground=BUTTON_HOVER, disabledforeground=TEXT_DIM,
                       padx=8 if small else 14, pady=3 if small else 5, radius=6)


class TrainerWindow:
    def __init__(self, root: tk.Misc, keys, geometry: dict, geometry_name: str, statistic: dict,
                 hard_ngrams: list[tuple[str, float]] | None = None):
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
        self.hard_ngrams = hard_ngrams or []
        self.mode = saved.get("trainer_mode", "words")
        if self.mode not in ("words", "ngrams") or (self.mode == "ngrams" and not self.hard_ngrams):
            self.mode = "words"
        self.auto_level = saved.get("trainer_auto_level", True)
        self.done_lines = []        # (cpm, accuracy) завершених рядків цієї сесії
        self.level_lines = []       # ... лише на поточному рівні (для «Сам підвищуй»)
        self.stats = trainer.load_stats(geometry_name)
        self._merged = True         # поточну сесію вже додано до статистики

        self.win = tk.Toplevel(root)
        self.win.title("Тренування")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(root)
        self._build()
        self.toasts = Toasts(self.win)
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
            if mode == "quotes" or (mode == "ngrams" and not self.hard_ngrams):
                b.config(state="disabled")
            tooltip.add(b, tip if mode != "quotes" else "Скоро: цілі цитати Франка, Лесі Українки, "
                                                         "Коцюбинського, Стефаника…")
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
        self.button_auto = _button(lv, "", self._toggle_auto)
        self.button_auto.pack(side="right")
        tooltip.add(self.button_auto, "Сам підвищуй: коли останні "
                    f"{trainer.LEVEL_UP_LINES} рядки на рівні — з точністю від "
                    f"{trainer.LEVEL_UP_ACCURACY:.0f}% і рівною швидкістю (розкид до "
                    f"{trainer.LEVEL_UP_SPREAD * 100:.0f}%), відкривається наступна порція літер.\n"
                    "Вимкнено — рівень лише повзунком.")
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
        self.weak_label = tk.Label(w, bg=BG, fg=TEXT_DIM, font=(FONT, 10), anchor="w", justify="left")
        self.weak_label.pack(fill="x", padx=16, pady=(0, 6), before=bottom)
        tooltip.add(self.weak_label, "Найслабші літери за всі тренування на цій клавіатурі "
                                     f"(від {trainer.MIN_SAMPLES} натискань): точність і середній час "
                                     "від попередньої літери. Слабкість — помилки, потім повільність.")
        close = _button(bottom, "Закрити", self.close, small=False)
        close.pack(side="right")
        tooltip.add(close, "Закрити тренування (Esc). Рівень і переклад запам'ятовуються.")
        again = _button(bottom, "Інший рядок", self._new_line, small=False)
        again.pack(side="right", padx=(0, 8))
        tooltip.add(again, "Пропустити цей рядок і взяти новий.")
        reset = _button(bottom, "Скинути статистику", self._reset_stats, small=False)
        reset.pack(side="right", padx=(0, 8))
        tooltip.add(reset, "Забути статистику по літерах для цієї клавіатури (спитає ще раз). "
                           "Варто, коли розкладку суттєво змінено.")
        self._update_translate_button()
        self._update_auto_button()
        self._update_mode_buttons()

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

    def _update_auto_button(self):
        self.button_auto.config(text="Сам підвищуй: так" if self.auto_level else "Сам підвищуй: ні")

    def _toggle_auto(self):
        self.auto_level = not self.auto_level
        settings.save(trainer_auto_level=self.auto_level)
        self._update_auto_button()

    def _update_mode_buttons(self):
        for mode, b in self.mode_buttons.items():
            on = mode == self.mode
            b.config(bg=ACCENT if on else BUTTON, fg=KEY_TEXT if on else TEXT,
                     activebackground=ACCENT if on else BUTTON_HOVER)

    def _set_mode(self, mode):
        self.mode = mode
        settings.save(trainer_mode=mode)
        self._update_mode_buttons()
        self._new_line()

    def _reset_stats(self):
        if not messagebox.askyesno("Статистика", "Забути статистику по літерах для цієї клавіатури?",
                                   parent=self.win):
            return
        self.stats = {}
        self._merged = True                     # і поточний рядок не рахувати
        trainer.save_stats(self.geometry_name, self.stats)
        self._show_weak()

    def _merge_session(self):
        """Натискання поточного рядка -> статистика (раз на рядок, і для недодрукованого)."""
        if self._merged or not hasattr(self, "session"):
            return
        self._merged = True
        if self.session.pos or self.session.errors:
            trainer.merge_stats(self.stats, self.session)
            trainer.save_stats(self.geometry_name, self.stats)

    def _show_weak(self):
        weak = trainer.weak_letters(self.stats, set(self.order))
        if not weak:
            self.weak_label.config(text="Слабкі літери: ще замало натискань")
            return
        parts = [f"{ch} {acc:.0f}%" + (f" {ms:.0f} мс" if ms else "") for ch, acc, ms in weak]
        self.weak_label.config(text="Слабкі літери: " + " · ".join(parts))

    def _on_level(self, value):
        level = int(float(value))
        if level == self.level and hasattr(self, "session"):
            return
        self.level = level
        self.level_lines = []
        levels = {**settings.load().get("trainer_levels", {}), self.geometry_name: level}
        settings.save(trainer_levels=levels)
        if hasattr(self, "session"):
            self._new_line()

    # ------------------------------------------------------------------
    def _new_line(self):
        self._merge_session()
        self.allowed = trainer.letters_at(self.order, self.level)
        self.focus = self.allowed[-1] if self.level > 0 else None
        n, total = len(self.allowed), len(self.order)
        targets = trainer.hard_targets(self.hard_ngrams, self.allowed) if self.mode == "ngrams" else []
        if targets:
            text = self.source.ngram_line(targets, self.allowed)
            info = " · " + " ".join(g for g, _ in targets[:6]) + ("…" if len(targets) > 6 else "")
        else:
            text = self.source.line(self.allowed, self.focus)
            info = f" · нова: «{self.focus}»" if self.focus else " · домашній ряд"
            if self.mode == "ngrams":
                info += " · важких поєднань з цих літер нема"
        self.session = trainer.Session(text)
        self._merged = False
        self.letters_label.config(text=f"{n} з {total}{info}")
        self._paint_board()
        self._render()
        self._show_stats()
        self._show_weak()

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
            line = (s.cpm(time.monotonic()), s.accuracy())
            self.done_lines.append(line)
            self.level_lines.append(line)
            if self.auto_level and self.level < self.levels - 1 and trainer.should_level_up(self.level_lines):
                self.scale.set(self.level + 1)       # -> _on_level -> новий рядок
                self.win.update_idletasks()
                self._on_level(self.level + 1)
                self.toasts.show(f"Рівень вище: нова літера «{self.allowed[-1]}»"
                                 if self.focus else "Рівень вище")
                return "break"
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
        self._merge_session()
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
