"""Неблокувальні сповіщення в головному вікні (жовті плашки справа вгорі).

Замість messagebox.showinfo там, де юзеру треба лише знати, що сталось
(«записано», «ваги змінились»): нічого не блокують, зникають самі (не довше
MAX_MS; поки над плашкою курсор — не зникають), клік — закрити одразу. Питання і помилки лишаються модальними.

    toasts = Toasts(root); toasts.show("Записано 12 клавіш у CYR")
"""

import tkinter as tk

from uiux.theme import DROP_BLOCKED, FONT, FROZEN_FG, KEY_TEXT, px

COLORS = {"info": FROZEN_FG, "error": DROP_BLOCKED}
GAP = 6
MAX_MS = 3000      # автор (2026-11-26): плашки — не довше 3 с
HOVER_POLL_MS = 250
AFTER_HOVER_MS = 1000


def _hovered(widget) -> bool:
    """Курсор над віджетом (з дочірніми)."""
    try:
        px_, py_ = widget.winfo_pointerxy()
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        return x <= px_ < x + widget.winfo_width() and y <= py_ < y + widget.winfo_height()
    except tk.TclError:
        return False


def auto_close(widget, ms: int, close) -> None:
    """close() через ms; якщо тоді над widget курсор — чекати, доки піде, і закрити
    через AFTER_HOVER_MS (повернувся — знову чекати). Віджет уже знищено — нічого."""
    def check(grace_done=False):
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return
        if _hovered(widget):
            widget.after(HOVER_POLL_MS, check)
        elif not grace_done:
            widget.after(AFTER_HOVER_MS, lambda: check(grace_done=True))
        else:
            close()
    widget.after(ms, lambda: close() if not _hovered(widget) else check())


class Toasts:
    def __init__(self, root, top: int = 8, right: int = 16):
        self.root = root
        self.top, self.right = top, right
        self.items: list[tk.Frame] = []

    def show(self, text: str, kind: str = "info", ms: int | None = None) -> tk.Frame:
        bg = COLORS.get(kind, COLORS["info"])
        frame = tk.Frame(self.root, bg=bg, cursor="hand2")
        label = tk.Label(frame, text=text, bg=bg, fg=KEY_TEXT, font=(FONT, 10, "bold"),
                         justify="left", anchor="w", wraplength=px(440), padx=px(12), pady=px(8))
        label.pack(side="left")
        close = tk.Label(frame, text="✕", bg=bg, fg=KEY_TEXT, font=(FONT, 10, "bold"), padx=px(8))
        close.pack(side="right", anchor="n", pady=px(6))
        for widget in (frame, label, close):
            widget.bind("<Button-1>", lambda _e, f=frame: self.close(f))
        self.items.append(frame)
        self._layout()
        lines = text.count("\n") + 1
        wait = min(MAX_MS, ms if ms is not None else 5000 + 1500 * lines)
        auto_close(frame, wait, lambda: self.close(frame))
        return frame

    def close(self, frame) -> None:
        if frame in self.items:
            self.items.remove(frame)
            frame.destroy()
            self._layout()

    def _layout(self) -> None:
        y = self.top
        for frame in self.items:
            frame.place(relx=1.0, x=-self.right, y=y, anchor="ne")
            frame.lift()
            frame.update_idletasks()
            y += frame.winfo_reqheight() + GAP
