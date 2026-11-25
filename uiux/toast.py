"""Неблокувальні сповіщення в головному вікні (жовті плашки справа вгорі).

Замість messagebox.showinfo там, де юзеру треба лише знати, що сталось
(«записано», «ваги змінились»): нічого не блокують, зникають самі,
клік — закрити одразу. Питання і помилки лишаються модальними.

    toasts = Toasts(root); toasts.show("Записано 12 клавіш у CYR")
"""

import tkinter as tk

from uiux.theme import DROP_BLOCKED, FONT, FROZEN_FG, KEY_TEXT, px

COLORS = {"info": FROZEN_FG, "error": DROP_BLOCKED}
GAP = 6


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
        self.root.after(ms if ms is not None else 5000 + 1500 * lines, lambda: self.close(frame))
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
