"""Підказки при наведенні (тултіпи) — для тих, хто не читає мануал.

Малюються всередині головного вікна (place), як і жовті плашки
(uiux/toast.py): без окремих Toplevel, з якими віконні менеджери
поводяться по-різному. З'являються після паузи, ховаються, щойно курсор
пішов або натиснуто кнопку миші.
"""

import tkinter as tk

from uiux.theme import FONT, TEXT

DELAY_MS = 600
BG = "#2f3542"
BORDER = "#4a5263"


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text = widget, text
        self._job = None
        self._tip = None
        # add="+": не перебиваємо hover самої кнопки (RoundButton)
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._job = self.widget.after(DELAY_MS, self._show)

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self):
        self._job = None
        if not self.text or not self.widget.winfo_exists():
            return
        root = self.widget.winfo_toplevel()
        self._tip = tk.Label(root, text=self.text, bg=BG, fg=TEXT, font=(FONT, 10),
                             justify="left", wraplength=360, padx=10, pady=6,
                             highlightthickness=1, highlightbackground=BORDER)
        root.update_idletasks()
        w, h = self._tip.winfo_reqwidth(), self._tip.winfo_reqheight()
        x = self.widget.winfo_rootx() - root.winfo_rootx()
        y = self.widget.winfo_rooty() - root.winfo_rooty() + self.widget.winfo_height() + 4
        if y + h > root.winfo_height():          # знизу не влазить — над віджетом
            y = self.widget.winfo_rooty() - root.winfo_rooty() - h - 4
        x = max(4, min(x, root.winfo_width() - w - 4))
        self._tip.place(x=x, y=max(4, y))
        self._tip.lift()

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def add(widget: tk.Widget, text: str) -> Tooltip:
    return Tooltip(widget, text)
