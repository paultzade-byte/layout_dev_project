"""Міні-апка статистики: тека з текстами -> statistic.json + word_stats.json.

    python -m uiux.stats_app [ТЕКА_З_ТЕКСТАМИ]

Юзер вибирає теку (читаються всі .txt, з підтеками) і куди зберегти; мову
апка визначає сама (можна змінити), далі — Старт. Підрахунок — core/corpus.py
у фоновому потоці (воркери — окремі процеси), з обмеженням CPU з меню.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from config import settings
from config.paths import layouts_dir
from core import corpus
from uiux.theme import ACCENT, BG, BUTTON, BUTTON_HOVER, FONT, KEY_TEXT, PANEL, TEXT, TEXT_DIM
from uiux.toast import Toasts
from uiux.tooltip import Tooltip
from uiux.widgets import RoundButton

CPU_CHOICES = (25, 50, 75, 100)     # % усієї машини (не одного ядра, як в оптимізаторі)
AUTO = "auto"


def _button(parent, text, command):
    return RoundButton(parent, text=text, command=command, font=(FONT, 10), bg=BUTTON, fg=TEXT,
                       activebackground=BUTTON_HOVER, parent_bg=parent.cget("bg"))


def _size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024


def _duration(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h} год {m:02d} хв" if h else f"{m} хв {s:02d} с" if m else f"{s} с"


class StatsApp:
    def __init__(self, root: tk.Tk, corpus_dir: str | None = None):
        self.root = root
        root.title("Статистика текстів — ukr-layout")
        root.configure(bg=BG)
        root.resizable(False, False)
        saved = settings.load()
        self.corpus_dir = Path(corpus_dir) if corpus_dir else (
            Path(saved["stats_corpus"]) if saved.get("stats_corpus") else None)
        self.out_dir = Path(saved.get("stats_out") or layouts_dir() / "статистика")
        self.cpu = saved.get("stats_cpu", 25)
        self.lang = AUTO
        self.detected: str | None = None
        self.files: list[Path] = []
        self.worker: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.events: queue.Queue = queue.Queue()   # з фонового потоку — лише сюди
        self.toasts = Toasts(root)
        self._build()
        self._scan()

    # ------------------------------------------------------------ вигляд

    def _build(self):
        pad = dict(padx=14, pady=6)
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        def row(title, tip):
            frame = tk.Frame(body, bg=BG)
            frame.pack(fill="x", **pad)
            label = tk.Label(frame, text=title, bg=BG, fg=TEXT_DIM, font=(FONT, 10), width=14, anchor="w")
            label.pack(side="left")
            Tooltip(label, tip)
            return frame

        f = row("Тексти", "Тека з текстами для аналізу. Читаються всі файли .txt (UTF-8), разом з підтеками.")
        self.label_corpus = tk.Label(f, bg=PANEL, fg=TEXT, font=(FONT, 10), anchor="w", width=48, padx=8, pady=4)
        self.label_corpus.pack(side="left")
        Tooltip(self.label_corpus, lambda: str(self.corpus_dir or "Теку ще не вибрано"))
        self.button_corpus = _button(f, "Вибрати теку…", self.pick_corpus)
        self.button_corpus.pack(side="left", padx=(8, 0))
        Tooltip(self.button_corpus, "Вибрати теку з текстами (.txt).")

        f = row("Знайдено", "Скільки файлів .txt знайдено у вибраній теці і їхній загальний розмір.")
        self.label_found = tk.Label(f, bg=BG, fg=TEXT, font=(FONT, 10), anchor="w")
        self.label_found.pack(side="left")
        Tooltip(self.label_found, "Файли .txt у вибраній теці (з підтеками). Інші формати пропускаються.")

        f = row("Мова", "Мова текстів — від неї залежить алфавіт (які символи рахуються).")
        self.button_lang = _button(f, "", self.show_lang_menu)
        self.button_lang.pack(side="left")
        Tooltip(self.button_lang, "Мова визначається сама за характерними літерами (ї/є/ґ, ў, ą/ł…). "
                                  "Клік — вибрати вручну.")

        f = row("Зберегти в", "Тека, куди буде записано statistic.json і word_stats.json.")
        self.label_out = tk.Label(f, bg=PANEL, fg=TEXT, font=(FONT, 10), anchor="w", width=48, padx=8, pady=4)
        self.label_out.pack(side="left")
        Tooltip(self.label_out, lambda: f"{self.out_dir}\nФайли з такими назвами там буде перезаписано.")
        self.button_out = _button(f, "Змінити…", self.pick_out)
        self.button_out.pack(side="left", padx=(8, 0))
        Tooltip(self.button_out, "Вибрати теку для результату.")

        f = row("Хід", "Скільки вже прочитано і скільки лишилось.")
        self.bar = tk.Canvas(f, width=420, height=16, bg=PANEL, highlightthickness=0)
        self.bar.pack(side="left")
        Tooltip(self.bar, lambda: self.label_progress.cget("text") or "Ще не запущено.")
        self.label_progress = tk.Label(f, bg=BG, fg=TEXT_DIM, font=(FONT, 10), anchor="w", width=36)
        self.label_progress.pack(side="left", padx=(8, 0))
        Tooltip(self.label_progress, "Прочитано / усього, час і приблизно скільки лишилось.")

        f = tk.Frame(body, bg=BG)
        f.pack(fill="x", padx=14, pady=(12, 4))
        self.button_start = RoundButton(f, text="Старт", command=self.toggle, font=(FONT, 11, "bold"),
                                        bg=ACCENT, fg=KEY_TEXT, parent_bg=BG, padx=24)
        self.button_start.pack(side="left")
        Tooltip(self.button_start, self._start_tip)
        self.button_cpu = _button(f, "", self.show_cpu_menu)
        self.button_cpu.pack(side="right")
        Tooltip(self.button_cpu, "Яку частку процесора можна зайняти. Менше — повільніше, "
                                 "зате комп'ютер не гріється і не гальмує. Можна міняти до старту.")
        self._refresh()

    def _start_tip(self):
        if self.worker:
            return "Зупинити підрахунок (нічого не буде записано)."
        if not self.files:
            return "Спершу виберіть теку з файлами .txt."
        if self._lang_code() is None:
            return "Мову не вдалося визначити — виберіть її вручну."
        return "Порахувати статистику і записати statistic.json + word_stats.json."

    def _lang_code(self) -> str | None:
        return self.detected if self.lang == AUTO else self.lang

    def _refresh(self):
        self.label_corpus.config(text=self._short(self.corpus_dir) if self.corpus_dir else "— не вибрано —")
        self.label_out.config(text=self._short(self.out_dir))
        if self.lang == AUTO:
            name = corpus.LANGUAGES[self.detected].name if self.detected else "не визначено"
            self.button_lang.config(text=f"{name} (авто) ▾")
        else:
            self.button_lang.config(text=f"{corpus.LANGUAGES[self.lang].name} ▾")
        self.button_cpu.config(text=f"CPU: {self.cpu}% ▾")
        running = self.worker is not None
        self.button_start.config(text="Стоп" if running else "Старт",
                                 state="normal" if running or (self.files and self._lang_code()) else "disabled")
        for b in (self.button_corpus, self.button_out, self.button_lang, self.button_cpu):
            b.config(state="disabled" if running else "normal")

    @staticmethod
    def _short(path: Path, limit: int = 52) -> str:
        s = str(path)
        return s if len(s) <= limit else "…" + s[-(limit - 1):]

    def _draw_bar(self, frac: float):
        self.bar.delete("all")
        w = int(420 * max(0.0, min(1.0, frac)))
        if w:
            self.bar.create_rectangle(0, 0, w, 16, fill=ACCENT, width=0)

    # ------------------------------------------------------------ дії

    def pick_corpus(self):
        path = filedialog.askdirectory(parent=self.root, title="Тека з текстами (.txt)",
                                       initialdir=str(self.corpus_dir or Path.home()))
        if path:
            self.corpus_dir = Path(path)
            settings.save(stats_corpus=path)
            self._scan()

    def pick_out(self):
        path = filedialog.askdirectory(parent=self.root, title="Куди зберегти статистику",
                                       initialdir=str(self.out_dir if self.out_dir.exists() else layouts_dir()))
        if path:
            self.out_dir = Path(path)
            settings.save(stats_out=path)
            self._refresh()

    def _scan(self):
        self.files = corpus.find_corpus_files(self.corpus_dir) if self.corpus_dir and self.corpus_dir.is_dir() else []
        total = sum(f.stat().st_size for f in self.files)
        self.label_found.config(text=f"{len(self.files)} файлів .txt, {_size(total)}" if self.files
                                else "немає файлів .txt" if self.corpus_dir else "—")
        self.detected = corpus.detect_language(self.files) if self.files else None
        self._draw_bar(0)
        self.label_progress.config(text="")
        self._refresh()

    def show_lang_menu(self):
        menu = self._menu()
        auto = corpus.LANGUAGES[self.detected].name if self.detected else "не визначено"
        menu.add_command(label=f"{'✓ ' if self.lang == AUTO else '    '}Авто ({auto})",
                         command=lambda: self._set_lang(AUTO))
        for code, lang in corpus.LANGUAGES.items():
            menu.add_command(label=f"{'✓ ' if self.lang == code else '    '}{lang.name}",
                             command=lambda c=code: self._set_lang(c))
        self._popup(menu, self.button_lang)

    def _set_lang(self, code):
        self.lang = code
        self._refresh()

    def show_cpu_menu(self):
        menu = self._menu()
        for p in CPU_CHOICES:
            note = "  (усі ядра)" if p == 100 else ""
            menu.add_command(label=f"{'✓ ' if p == self.cpu else '    '}{p}%{note}",
                             command=lambda p=p: self._set_cpu(p))
        self._popup(menu, self.button_cpu)

    def _set_cpu(self, p):
        self.cpu = p
        settings.save(stats_cpu=p)
        self._refresh()

    def _menu(self):
        return tk.Menu(self.root, tearoff=0, bg=BUTTON, fg=TEXT, activebackground=ACCENT,
                       activeforeground=KEY_TEXT, font=(FONT, 10), bd=0)

    @staticmethod
    def _popup(menu, button):
        menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    def toggle(self):
        if self.worker:
            self.stop_flag.set()
            self.label_progress.config(text="зупиняю…")
            return
        lang = self._lang_code()
        if not (self.files and lang):
            return
        self.stop_flag.clear()
        files, out_dir, share = list(self.files), self.out_dir, self.cpu / 100
        self.worker = threading.Thread(target=self._run, args=(files, lang, out_dir, share), daemon=True)
        self._draw_bar(0)
        self.label_progress.config(text="готую…")
        self.worker.start()
        self._refresh()
        self.root.after(100, self._poll)

    def _poll(self):
        """Забирає з черги хід і результат фонового потоку (Tk — лише з головного)."""
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "progress":
                    frac, text = data
                    self._draw_bar(frac)
                    self.label_progress.config(text=text)
                else:
                    self._finished(*data)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _run(self, files, lang, out_dir, share):
        """Фоновий потік: Tk не чіпає, усе — через self.events."""
        def progress(p: corpus.Progress):
            left = p.elapsed / p.fraction * (1 - p.fraction) if p.fraction > 0 else 0
            text = f"{p.fraction:.0%} · {_duration(p.elapsed)} · лишилось ~{_duration(left)}"
            self.events.put(("progress", (p.fraction, text)))
        try:
            result = corpus.count_corpus(files, lang, share, progress, self.stop_flag.is_set)
            stat, words = corpus.write_outputs(result, out_dir)
            msg, kind = f"Готово: {stat.name} і {words.name} у\n{out_dir}", "info"
        except corpus.Stopped:
            msg, kind = "Зупинено — нічого не записано.", "info"
        except Exception as e:      # показати, а не мовчки померти в потоці
            msg, kind = f"Помилка: {e}", "error"
        self.events.put(("done", (msg, kind)))

    def _finished(self, msg, kind):
        self.worker = None
        if kind != "info" or msg.startswith("Зупинено"):
            self._draw_bar(0)
            self.label_progress.config(text="")
        self.toasts.show(msg, kind)
        self._refresh()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    StatsApp(root, argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
