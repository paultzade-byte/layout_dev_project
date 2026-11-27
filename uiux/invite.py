"""Інвітейшн при вході: м'яка жовта плашка — сіре «Гасло дня» і фраза кампанії «Пізнай себе».

    invite = Invite(root, launch)     # launch — номер дня з запуском (next_launch, settings.json)

Показується першою, поки головне вікно будується сховане (main у uiux/app.py), —
прикриває його мигання на старті. Закривається кліком (або Esc / Enter / пробіл), сама — за CLOSE_MS (поки над нею курсор — ні).
Тексти й етапи — від автора (2026-11-25); на плашці лише «Гасло дня» і фраза (автор: «забагато
тексту»), етапи — для довідки в коді.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date

from uiux.theme import FONT, KEY_TEXT, px
from uiux.toast import auto_close

BG = "#fbe9be"            # м'який жовтий
BORDER = "#e0c27a"
DIM = "#7a6a45"
CLOSE_MS = 5000          # автор (2026-11-26): не закрили кліком — зникає сама

CAMPAIGN = "Кампанія «Пізнай себе»"
# (з якого запуску, етап, фраза); діє до наступного запису
PHRASES = [
    (1, "Етап I. Знайомство та дисципліна", "«Пізнай себе, друкуй»."),
    (11, "Етап II. Мотивація та саморозвиток", "«Пізнай себе, друкуй як восьминіг» 🐙"),
    (14, "Етап II. Мотивація та саморозвиток", "«Пізнай себе, друкуй, навіть якщо не впевнений»."),
    (17, "Етап II. Мотивація та саморозвиток", "«Пізнай себе, друкуй, доки є світло»."),
    (20, "Етап II. Мотивація та саморозвиток", "«Пізнай себе, друкуй, якщо любиш»."),
    (23, "Етап II. Мотивація та саморозвиток", "«Пізнай себе, друкуй швидше за ШІ» 🤖"),
    (26, "Етап II. Мотивація та саморозвиток", "«Пізнай себе, друкуй як заманеться»."),
    (29, "Етап III. Професійна самореалізація", "«Пізнай себе, друкуй як друкар»."),
    (32, "Етап III. Професійна самореалізація", "«Пізнай себе, друкуй як друкарська машинка»."),
    (35, "Етап III. Професійна самореалізація", "«Пізнай себе, друкуй, ти, хто все зрозумів»."),
    (38, "Етап III. Професійна самореалізація", "«Пізнай себе, друкуй. Або не друкуй. Твоя воля»."),
    (41, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як мокрий принтер»."),
    (42, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй проти годинникової стрілки»."),
    (43, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стенографіст»."),
    (44, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стеногр@фіст»."),
    (45, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стенографік»."),
    (46, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стенограма»."),
    (47, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стеногравій»."),
    (48, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стереограф»."),
    (49, "Етап IV. Перші ознаки відхилень", "«Пізнай себе, друкуй як стереографін»."),
    (50, "Етап V. Апогей апофеозу абсурду", "«Пізнай себе, друкуй як восьминіг-стенографіст»."),
    (51, "Етап V. Апогей апофеозу абсурду", "«Пізнай себе, друкуй як восьминогічний стенографіст»."),
    (52, "Етап V. Апогей апофеозу абсурду", "«Пізнай себе, друкуй як стенографічний восьминогізм»."),
    (53, "Етап VI. Постійна просвітленість", "«Пізнай себе»."),
]


def phrase(launch: int) -> tuple[str, str]:
    """(етап, фраза) для номера дня з запуском (з 1)."""
    stage, text = PHRASES[0][1:]
    for start, s, t in PHRASES:
        if launch >= start:
            stage, text = s, t
    return stage, text


def next_launch(today: date | None = None) -> int:
    """Номер гасла: скільки різних днів програму запускали (settings.json `launch_count` +
    `launch_date`). Автор (2026-11-26): гасло дня — одне на день; повторні запуски того самого
    дня лічильник не міняють, дні без запусків — теж (наступний запуск = наступне гасло)."""
    from config import settings
    today = (today or date.today()).isoformat()
    data = settings.load()
    n = int(data.get("launch_count", 0))
    if data.get("launch_date") != today or n == 0:
        n += 1
        settings.save(launch_count=n, launch_date=today)
    return n


class Invite:
    def __init__(self, root: tk.Misc, launch: int):
        _, text = phrase(launch)
        self.win = w = tk.Toplevel(root)
        w.overrideredirect(True)            # без рамки вікна
        w.configure(bg=BORDER)
        try:
            w.attributes("-topmost", True)
        except tk.TclError:
            pass
        body = tk.Frame(w, bg=BG, padx=px(34), pady=px(22))
        body.pack(padx=px(2), pady=px(2))
        labels = [
            tk.Label(body, text="Гасло дня", bg=BG, fg=DIM, font=(FONT, 11)),
            tk.Label(body, text=text, bg=BG, fg=KEY_TEXT, font=(FONT, 20, "bold"), wraplength=px(560),
                     justify="center"),
        ]
        pads = [(0, 6), (0, 0)]
        for label, pad in zip(labels, pads):
            label.pack(pady=pad)
        for widget in (w, body, *labels):
            widget.bind("<Button-1>", lambda e: self.close())
            widget.configure(cursor="hand2")
        for key in ("<Escape>", "<Return>", "<space>"):
            w.bind(key, lambda e: self.close())
        w.update_idletasks()
        x = (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2
        y = (w.winfo_screenheight() - w.winfo_reqheight()) // 3
        w.geometry(f"+{x}+{y}")
        w.update()
        try:
            w.focus_force()
        except tk.TclError:
            pass
        auto_close(w, CLOSE_MS, self.close)

    @property
    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def lift(self):
        if self.alive:
            self.win.lift()
            self.win.focus_force()

    def close(self):
        if self.alive:
            self.win.destroy()
