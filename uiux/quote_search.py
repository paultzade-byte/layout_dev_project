"""Пошук цитати для «Класики» тренажера: кнопка-лупа і модальне вікно зі списком.

    search_button(parent, command)  — лупа у верхньому ряду тренажера (Canvas, без емодзі:
                                      Tk на X11 падає на кольорових емодзі-шрифтах)
    open_search(trainer_window)     — вікно пошуку поверх тренажера (uiux/trainer.py);
                                      вже відкрите (подвійний клік по лупі) — лише на передній план

Пошук — core.trainer.search_quotes (початки слів тексту, автора, твору). Вибір —
TrainerWindow._select_quote(quote). Поки вікно відкрите, тренажер чекає (grab); після
закриття grab і фокус повертаються тренажеру (він сам модальний над головним вікном).
"""

from __future__ import annotations

import tkinter as tk

from core import trainer
from uiux import tooltip
from uiux.theme import ACCENT, BG, BUTTON, BUTTON_HOVER, FONT, KEY_TEXT, PANEL, TEXT, TEXT_DIM, px
from uiux.toast import Toasts
from uiux.widgets import _rounded

LIST_W = 640            # ширина списку, px (до масштабу)
LIST_ROWS = 16
LIST_FONT = (FONT, 10)
ENTRY_FONT = (FONT, 11)
BUTTON_TIP = ("Пошук цитати…\nЗа словами з тексту, автором чи назвою твору: досить початку слова "
              "(«ліс» знайде «лісова», «лісі»), кілька слів — мають бути всі. Вибрана цитата "
              "одразу йде у «Класику».")


class SearchButton(tk.Canvas):
    """Кнопка з намальованою лупою (коло + ручка), як RoundButton: hover, рука-курсор."""

    def __init__(self, parent, command):
        font = (FONT, 9, "bold")      # як малі кнопки тренажера (_button у uiux/trainer.py)
        h = int(parent.tk.call("font", "metrics", font, "-linespace")) + 2 * px(3)
        w = h + px(10)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, cursor="hand2",
                         bg=parent.cget("bg"))
        self.command, self.w, self.h = command, w, h
        self._hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def _click(self, event):
        if 0 <= event.x < self.w and 0 <= event.y < self.h and self.command:
            self.command()

    def _draw(self):
        w, h = self.w, self.h
        self.delete("all")
        self.create_polygon(_rounded(0, 0, w, h, min(px(6), h // 2)), smooth=True,
                            fill=BUTTON_HOVER if self._hover else BUTTON, outline="")
        r = h * 0.24
        cx, cy = w / 2 - r * 0.35, h / 2 - r * 0.35
        line = max(2, px(2))
        self.create_oval(cx - r, cy - r, cx + r, cy + r, outline=TEXT, width=line)
        k = 0.7071                     # ручка — під 45° від кола вниз праворуч
        self.create_line(cx + r * k, cy + r * k, cx + r * 2.1 * k + px(1), cy + r * 2.1 * k + px(1),
                         fill=TEXT, width=line + 1, capstyle="round")


def search_button(parent, command) -> SearchButton:
    b = SearchButton(parent, command)
    tooltip.add(b, BUTTON_TIP)
    return b


class RowTooltip(tooltip.Tooltip):
    """Підказка списку: текст — про рядок під курсором; рядок змінився — підказка заново."""

    def __init__(self, listbox: tk.Listbox, text_for_row, empty_text: str):
        self.listbox, self.text_for_row, self.empty_text = listbox, text_for_row, empty_text
        self.row = None
        self._showing = False
        super().__init__(listbox, self._text)
        listbox.bind("<Motion>", self._on_motion, add="+")

    def view_changed(self):
        """Список прокручено чи заповнено заново (коліщатко, ↑ ↓, новий пошук): під курсором
        уже інша цитата — підказку сховати (на Windows коліщатко — не ButtonPress)."""
        if self._showing:              # update_idletasks усередині _show — не ховати свою ж
            return
        self.row = None
        self._hide()

    def _row_at(self, y) -> int | None:
        lb = self.listbox
        if not lb.size():
            return None
        i = lb.nearest(y)
        box = lb.bbox(i)
        return i if box and box[1] <= y < box[1] + box[3] + 2 else None

    def _pointer_row(self):
        lb = self.listbox
        return self._row_at(lb.winfo_pointery() - lb.winfo_rooty())

    def _on_motion(self, event):
        row = self._row_at(event.y)
        if row != self.row:
            self.row = row
            self._hide()
            self._schedule()

    def _text(self):
        self.row = self._pointer_row()
        return self.empty_text if self.row is None else self.text_for_row(self.row)

    def _show(self):
        self._showing = True
        try:
            super()._show()
        finally:
            self._showing = False
        if self._tip is None or self.row is None:
            return
        box = self.listbox.bbox(self.row)          # під рядком, а не під усім списком
        if not box:
            return
        root = self.listbox.winfo_toplevel()
        top = self.listbox.winfo_rooty() - root.winfo_rooty() + box[1]
        h = self._tip.winfo_reqheight()
        y = top + box[3] + px(6)
        if y + h > root.winfo_height():
            y = top - h - px(4)
        self._tip.place_configure(y=max(4, y))


class QuoteSearch:
    def __init__(self, tw):
        self.tw = tw
        self.quotes = tw.quotes
        self.letters = list(tw.order)
        self.missing = {id(q): trainer.missing_letters(q, self.letters) for q in self.quotes}
        self.shown: list[dict] = []
        self.sel = None              # індекс вибраного рядка в self.shown

        self.win = tk.Toplevel(tw.win)
        tw.quote_search = self        # одразу: другий клік по лупі, поки вікно з'являється
        self.win.title("Пошук цитати")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.transient(tw.win)
        self._build()
        self.toasts = Toasts(self.win)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._fill(prefer=tw.quote if tw.mode == "quotes" else None)
        self._center()
        self.win.wait_visibility()
        self.win.grab_set()                   # тренажер чекає, доки вікно відкрите
        self.entry.focus_force()

    # ------------------------------------------------------------------
    def _build(self):
        w = self.win
        top = tk.Frame(w, bg=BG)
        top.pack(fill="x", padx=px(16), pady=(px(14), px(6)))
        label = tk.Label(top, text="Шукати:", bg=BG, fg=TEXT_DIM, font=(FONT, 10))
        label.pack(side="left")
        self.query = tk.StringVar()
        self.entry = tk.Entry(top, textvariable=self.query, font=ENTRY_FONT, bg=PANEL, fg=TEXT,
                              insertbackground=TEXT, relief="flat", highlightthickness=1,
                              highlightbackground=BUTTON, highlightcolor=ACCENT, width=36)
        self.entry.pack(side="left", padx=(px(8), 0), ipady=px(3))
        entry_tip = ("Слова з тексту цитати, автор чи твір. Досить початку слова: «ліс» знайде "
                     "«лісова», «лісі». Кілька слів — мають бути всі («франко лис»). Великі літери "
                     "й апострофи не важать. Порожньо — усі цитати.\n"
                     "↑ ↓ — по списку, Enter — друкувати, Esc — закрити.")
        tooltip.add(label, entry_tip)
        tooltip.add(self.entry, entry_tip)
        self.count_label = tk.Label(top, bg=BG, fg=TEXT_DIM, font=(FONT, 10))
        self.count_label.pack(side="right")
        tooltip.add(self.count_label, "Скільки цитат знайдено з усіх. Сірі — не набрати цією "
                                      "розкладкою (бракує літер), їх не вибрати.")

        mid = tk.Frame(w, bg=BG)
        mid.pack(padx=px(16), pady=(px(2), px(8)))
        zero = int(w.tk.call("font", "measure", LIST_FONT, "0")) or 7
        self.list_px = px(LIST_W)
        self.listbox = tk.Listbox(mid, width=self.list_px // zero, height=LIST_ROWS, font=LIST_FONT,
                                  bg=PANEL, fg=TEXT, selectbackground=ACCENT, selectforeground=KEY_TEXT,
                                  activestyle="none", relief="flat", bd=0, highlightthickness=0,
                                  exportselection=False, selectmode="browse")
        self.listbox.pack(side="left")
        bar = tk.Scrollbar(mid, orient="vertical", command=self.listbox.yview, bg=BUTTON,
                           troughcolor=BG, activebackground=BUTTON_HOVER, highlightthickness=0, bd=0)
        bar.pack(side="left", fill="y")
        self.row_tip = RowTooltip(self.listbox, self._row_tip,
                                  "Цитати, що підходять під пошук. Двічі клацни чи Enter — друкувати.")

        def scrolled(*args):
            bar.set(*args)
            self.row_tip.view_changed()
        self.listbox.config(yscrollcommand=scrolled)
        tooltip.add(bar, "Прокрутка списку (або коліщатко миші над ним).")

        bottom = tk.Frame(w, bg=BG)
        bottom.pack(fill="x", padx=px(16), pady=(0, px(14)))
        from uiux.trainer import _button          # ті самі кнопки, що в тренажері
        close = _button(bottom, "Закрити", self.close, small=False)
        close.pack(side="right")
        tooltip.add(close, "Закрити пошук, нічого не міняючи (Esc).")
        self.button_type = _button(bottom, "Друкувати", self.choose, small=False)
        self.button_type.pack(side="right", padx=(0, px(8)))
        tooltip.add(self.button_type, lambda: "Друкувати вибрану цитату в «Класиці» (Enter, подвійний клік)."
                    if self.sel is not None else "Спершу вибери цитату в списку (сірі не вибираються).")

        self.query.trace_add("write", lambda *a: self._fill())
        for widget in (self.entry, self.listbox):
            widget.bind("<Down>", lambda e: self._move(+1))
            widget.bind("<Up>", lambda e: self._move(-1))
            widget.bind("<Return>", lambda e: self.choose())
            widget.bind("<KP_Enter>", lambda e: self.choose())
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", self._on_double)

    # ------------------------------------------------------------------
    def _one_line(self, q) -> tuple[str, bool]:
        """Текст цитати в один рядок, обрізаний «…» під ширину списку; (рядок, чи обрізано)."""
        text = " ".join(q["text"].split())
        budget = self.list_px - px(14)
        measure = lambda t: int(self.win.tk.call("font", "measure", LIST_FONT, t))
        if measure(text) <= budget:
            return text, False
        lo, hi = 0, len(text)
        while lo < hi:                         # найдовший початок, що влазить разом із «…»
            mid = (lo + hi + 1) // 2
            if measure(text[:mid].rstrip() + "…") <= budget:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…", True

    def _fill(self, prefer=None):
        self.shown = trainer.search_quotes(self.quotes, self.query.get())
        lb = self.listbox
        lb.delete(0, "end")
        self.truncated = set()
        for i, q in enumerate(self.shown):
            line, cut = self._one_line(q)
            if cut:
                self.truncated.add(i)
            lb.insert("end", line)
            if self.missing[id(q)]:
                lb.itemconfig(i, fg=TEXT_DIM, selectbackground=PANEL, selectforeground=TEXT_DIM)
        blocked = sum(1 for q in self.shown if self.missing[id(q)])
        self.count_label.config(text=f"{len(self.shown)} з {len(self.quotes)}"
                                + (f" · {blocked} не набрати" if blocked else ""))
        ok = [i for i, q in enumerate(self.shown) if not self.missing[id(q)]]
        start = next((i for i in ok if self.shown[i] is prefer), ok[0] if ok else None)
        self._select(start)

    def _blocked(self, i) -> bool:
        return bool(self.missing[id(self.shown[i])])

    def _select(self, i):
        lb = self.listbox
        lb.selection_clear(0, "end")
        self.sel = i
        if i is not None:
            lb.selection_set(i)
            lb.activate(i)
            lb.see(i)
        self.button_type.config(state="normal" if i is not None else "disabled")

    def _move(self, step):
        """↑ ↓ — до сусіднього рядка, який можна вибрати (сірі пропускаються)."""
        n = len(self.shown)
        i = self.sel if self.sel is not None else (-1 if step > 0 else n)
        i += step
        while 0 <= i < n and self._blocked(i):
            i += step
        if 0 <= i < n:
            self._select(i)
        return "break"

    def _on_select(self, _event=None):
        cur = self.listbox.curselection()
        if not cur:
            return
        i = cur[0]
        if self._blocked(i):                   # сірий — не вибирається, лишаємо попередній
            self._select(self.sel)
            self.toasts.show(self._blocked_text(i))
        else:
            self._select(i)

    def _on_double(self, event):
        i = self.listbox.nearest(event.y)
        if 0 <= i < len(self.shown) and not self._blocked(i):
            self._select(i)
            self.choose()
        return "break"

    def _blocked_text(self, i) -> str:
        miss = ", ".join(f"«{ch}»" for ch in self.missing[id(self.shown[i])])
        return f"Не набрати цією розкладкою: нема {miss}"

    def _row_tip(self, i) -> str:
        if not 0 <= i < len(self.shown):
            return ""
        q = self.shown[i]
        parts = [trainer.quote_source(q)]
        if i in self.truncated:
            parts.append(" ".join(q["text"].split()))
        if self._blocked(i):
            parts.append(self._blocked_text(i) + ".")
        return "\n\n".join(p for p in parts if p)

    # ------------------------------------------------------------------
    def choose(self):
        """Друкувати вибрану цитату: закрити вікно і передати її тренажеру."""
        if self.sel is None:
            return "break"
        quote = self.shown[self.sel]
        self.close()
        self.tw._select_quote(quote)
        return "break"

    def _center(self):
        self.win.update_idletasks()
        top = self.tw.win
        x = top.winfo_rootx() + (top.winfo_width() - self.win.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + px(40)
        self.win.geometry(f"+{max(0, x)}+{max(0, y)}")

    def close(self):
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
        try:                                   # тренажер знову модальний над головним вікном
            self.tw.win.grab_set()
            self.tw.win.focus_force()
        except tk.TclError:
            pass


def open_search(tw) -> QuoteSearch:
    """Лупа тренажера: нове вікно пошуку або вже відкрите (не друге поверх першого)."""
    qs = getattr(tw, "quote_search", None)
    try:
        if qs is not None and qs.win.winfo_exists():
            qs.win.lift()
            return qs
    except tk.TclError:
        pass
    return QuoteSearch(tw)
