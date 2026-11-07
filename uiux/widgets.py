"""Кнопка із заокругленими кутами (у tk.Button кутів не заокруглити).

Підтримує те, чим апка користується з tk.Button: command, text, font, bg, fg,
activebackground, disabledforeground, padx, pady, state; config()/cget()/["state"].
"""

import tkinter as tk

_OWN = ("text", "command", "font", "bg", "fg", "activebackground", "disabledforeground",
        "padx", "pady", "state", "radius")


def _rounded(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class RoundButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, font=("TkDefaultFont", 10), bg="#2c313c",
                 fg="#ffffff", activebackground=None, disabledforeground="#888888",
                 padx=16, pady=6, radius=8, parent_bg=None):
        super().__init__(parent, highlightthickness=0, bd=0, cursor="hand2",
                         bg=parent_bg or parent.cget("bg"))
        self._o = dict(text=text, command=command, font=font, bg=bg, fg=fg,
                       activebackground=activebackground or bg, disabledforeground=disabledforeground,
                       padx=padx, pady=pady, state="normal", radius=radius)
        self._hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def _click(self, event):
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if inside and self._o["state"] == "normal" and self._o["command"]:
            self._o["command"]()

    def _draw(self):
        o = self._o
        # міряємо через tk-команди: об'єкти tkfont.Font, створені на кожне малювання,
        # прибираються вже після знищення інтерпретатора і валять процес (segfault)
        w = int(self.tk.call("font", "measure", o["font"], o["text"])) + 2 * o["padx"]
        h = int(self.tk.call("font", "metrics", o["font"], "-linespace")) + 2 * o["pady"]
        super().configure(width=w, height=h)
        self.delete("all")
        normal = o["state"] == "normal"
        fill = o["activebackground"] if (self._hover and normal) else o["bg"]
        self.create_polygon(_rounded(0, 0, w, h, min(o["radius"], h // 2)), smooth=True, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=o["text"], font=o["font"],
                         fill=o["fg"] if normal else o["disabledforeground"])
        super().configure(cursor="hand2" if normal else "")

    def configure(self, cnf=None, **kw):
        kw.update(cnf or {})
        own = {k: kw.pop(k) for k in list(kw) if k in _OWN}
        if kw:
            super().configure(**kw)
        if own:
            self._o.update(own)
            self._draw()

    config = configure

    def cget(self, key):
        return self._o[key] if key in self._o else super().cget(key)

    __getitem__ = cget
