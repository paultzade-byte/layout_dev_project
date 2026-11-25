
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
import math
import re
import sys
import threading
import time
from types import SimpleNamespace
import copy

from config.main_config import (MOVES_CONFIG, STATISTIC, ACTIVE, GEOMETRIES, GEOMETRY_TITLES, geometry_config,
                                load_moves, start_layout)
from config import settings
from config import stats_files
from core.layout_factory import build_layout, build_key_from_position
from core.models import Finger, Hand, Layout, Key
from core.scorer import MovementScoringEngine
from uiux.processors import OptimizationProcessor
from uiux import layer_view
from uiux.widgets import RoundButton
from uiux import render
from uiux.toast import Toasts
from uiux import tooltip
from core import knobs
from core import heat
from core import throttle
from core import export
from core.metrics import layout_metrics
from config.paths import layouts_dir
from pathlib import Path
# keeping this dead import for possible bedugging process
#from log.loggers.state_hasher import StateHasher

ZMK_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zmk"
# порядок кнопок перемикача: спершу «Звичайна» (для більшості людей)
GEOMETRIES_ORDER = ["generic_105_alpha", "corne_42"]
# режим, у якому є шари клавіатури і запис по USB (ZMK Studio)
ZMK_GEOMETRY = "corne_42"
# штраф показується в тій самій шкалі, що й у scripts/ (x1e8)
SCORE_SCALE = 1e8

from uiux.theme import (  # noqa: E402  (тема спільна з uiux/render.py)
    ACCENT, BG, BUTTON, BUTTON_HOVER, DROP_BLOCKED, DROP_OK, FINGER_COLORS, FONT, FROZEN_BG, FROZEN_FG,
    GROUP_COLORS, KEY_FONT, KEY_TEXT, PANEL, SLOT, TEXT, TEXT_DIM, blend, init_ui_scale, px, set_window_icon,
    ui_scale,
)


def style_key(widget, border: str | None = None, finger: Finger | None = None) -> None:
    """Єдине місце, де задається вигляд клавіші. Під час перетягування:
    border — рамка (DROP_OK / DROP_BLOCKED), finger — зона пальця, в яку
    клавіша потрапить (попередній перегляд кольору)."""
    key = widget.key
    # теплова мапа (core/heat.py): {position_id: {fill, ink, text}} — спільна для всіх клавіш
    heat_map = getattr(widget, "heat_map", None)
    cell = heat_map.get(key.position_id) if heat_map is not None else None
    if cell is not None:
        bg, fg = cell["fill"], cell["ink"]
    elif heat_map is not None and len(key.char) == 1 and key.char.strip():
        bg, fg = SLOT, TEXT_DIM            # літера без даних — сіра
    elif widget.is_frozen:
        bg, fg = FROZEN_BG, FROZEN_FG
    else:
        bg, fg = FINGER_COLORS.get(finger or key.finger, TEXT_DIM), KEY_TEXT
    border = border or (FROZEN_FG if widget.is_frozen else bg)
    # службові клавіші (Shft, SPA...) — підписи як на картинці (render.MOD_LABELS)
    text = getattr(widget, "labels", {}).get(key.char, key.char)
    font = KEY_FONT if len(text) <= 2 else (FONT, 11, "bold")
    widget.config(
        text=text, bg=bg, fg=fg, font=font,
        highlightthickness=px(2), highlightbackground=border, highlightcolor=border,
        # з тепловою мапою внизу відсоток — літеру вгору, щоб він не накривав хвостики (р, у, д)
        anchor="n" if cell is not None else "center", pady=px(4) if cell is not None else px(1),
    )
    # AltGr-символ клавіші (geometry["altgr"]: літера -> символ) — дрібно в
    # правому верхньому куті, як на картинці; іде за літерою при перетягуванні
    mark = getattr(widget, "altgr_label", None)
    if mark is not None:
        extra = "" if widget.is_frozen else getattr(widget, "altgr", {}).get(key.char, "")
        if extra:
            mark.config(text=extra, bg=bg, fg=fg)
            mark.place(relx=1.0, x=-px(5), y=px(2), anchor="ne")
        else:
            mark.place_forget()
    note = getattr(widget, "note_label", None)
    if note is not None:
        if cell is not None:
            note.config(text=cell["text"], bg=bg, fg=fg)
            note.place(relx=0.5, rely=1.0, y=-px(2), anchor="s")
        else:
            note.place_forget()
    # риска орієнтира (F/J, geometry "homing") — належить місцю, не літері:
    # після перетягування клавіша з новим position_id перемальовується
    homing = getattr(widget, "homing_mark", None)
    if homing is not None:
        if key.position_id in getattr(widget, "homing_ids", ()):
            homing.config(bg=fg)
            homing.place(relx=0.5, rely=1.0, y=-px(render.HOMING_BOTTOM + (11 if cell is not None else 0)),
                         anchor="s", width=px(render.HOMING_W), height=px(render.HOMING_H))
        else:
            homing.place_forget()


def make_button(parent, text, command, small=False, color=None):
    """Кнопка апки: заокруглена (uiux.widgets.RoundButton), hover — сама.
    color — кнопка групи: рамка і текст цього кольору, hover — його відтінок."""
    return RoundButton(
        parent, text=text, command=command, font=(FONT, 9 if small else 11, "bold"),
        bg=BUTTON, fg=color or TEXT, outline=color,
        activebackground=blend(color, BUTTON, 0.25) if color else BUTTON_HOVER, disabledforeground=TEXT_DIM,
        padx=8 if small else 16, pady=3 if small else 6, radius=6 if small else 8,
    )

def make_score_display(statistic, moves_config, engine=None):
    """engine — уже підготовлений (prepare_statistics) — щоб не рахувати двічі."""
    engine_holder = {"engine": engine} if engine is not None else {}

    def on_layout_changed(layout):
        engine = engine_holder.get("engine")
        if engine is None:
             # дорогий prepare_statistics() — рівно один раз, на перший виклик
             engine = MovementScoringEngine(layout.keys, moves_config)
             engine.prepare_statistics(statistic)
             engine_holder["engine"] = engine
        else:
            # усі наступні виклики — дешевий шлях, той самий, що і в SA-циклі
            engine.update_layout(layout.keys)
        score = engine.score().total_penalty

        return f"Штраф: {score / SCORE_SCALE:.2f}"
    return on_layout_changed


HEAT_TITLES = {"freq": "частота натискань, %", "pain": "незручність, % штрафу"}
YCUKEN_GEOMETRIES = {"generic_105_alpha"}  # де `default` позицій = ЙЦУКЕН
TITLE_ALLOWANCE = 70  # заголовок вікна + панель задач, px


# Підказки при наведенні (uiux/tooltip.py): «мануал мало хто читає»
KNOB_TIPS = {
    "home_row": "Наскільки тримати часті літери в домашньому (середньому) ряду, "
                "де пальці лежать у спокої.",
    "vertical": "Штраф, коли один палець набирає дві літери підряд з різних рядів "
                "(палець «стрибає» вгору-вниз).",
    "pinky": "Наскільки розвантажувати мізинці — найслабші пальці.",
    "alternation": "Ліворуч — більше перекатів (кілька літер підряд однією рукою), "
                   "праворуч — частіше чергувати руки.",
    "closeness": "Тримати літери ближче до звичних місць ЙЦУКЕН, щоб легше перевчитись. "
                 "Галочка вмикає, повзунок — наскільки сильно.",
}


class Slot:
    def __init__(self, position, x, y, width, height):
        slot_id = position["id"]
        self.id = slot_id
        self.x = x
        self.y = y
        self.width = width
        self.center_x = x + width / 2
        self.center_y = y + height / 2
        self.current_key = None  # the tkinter widget permanently anchored here
        self.finger = build_key_from_position(position).finger


class KeyLabel(tk.Label):
    key: Key
    is_frozen: bool
    current_slot: Slot


INNER_GAP = 6     # px між кнопками однієї групи
GROUP_GAP = 18    # px між групами щонайменше


class ButtonPanel:
     def __init__(
         self,
         root,
         logic
     ):
         self.root = root
         self.logic = logic
         # групи по 1–2 кнопки одного кольору (GROUP_COLORS): усередині групи INNER_GAP, між
         # групами — «пружини» (не менше GROUP_GAP, вільне місце порівну), тож ряд у будь-якому
         # режимі тягнеться від краю до краю дошки; сховану групу прибирає arrange()
         self.button_frame = tk.Frame(self.root, bg=BG)
         self.button_frame.pack(fill="x", padx=px(20), pady=(0, px(14)))
         group = lambda: tk.Frame(self.button_frame, bg=BG)
         kb, run, train, open_, save, picture = (group() for _ in range(6))
         self.groups = [kb, run, train, open_, save, picture]

         # клавіатура: шари <-> розкладка на екрані (scripts/zmk/keyboard_sync.py)
         self.keyboard_frame = kb
         self.button_kb_write = make_button(kb, "На клаву", self.logic.on_keyboard_write, color=GROUP_COLORS["keyboard"])
         self.button_kb_read = make_button(kb, "З клави", self.logic.on_keyboard_read, color=GROUP_COLORS["keyboard"])
         self.button_start = make_button(run, "Start", self.logic.toggle_optimization, color=GROUP_COLORS["run"])
         self.button_reheat = make_button(
             run, "Reheat",
             lambda: self.logic.processor.optimizer.reheat() if self.logic.processor.optimizer else None,
             color=GROUP_COLORS["run"])
         # тренажер друку на розкладці з дошки (uiux/trainer.py), модальне вікно
         self.button_train = make_button(train, "Тренування", self.logic.on_train, color=GROUP_COLORS["train"])
         # файли: розкладка (json) і картинка — завжди через діалог, юзер бачить куди
         self.button_open = make_button(open_, "Відкрити…", self.logic.on_open, color=GROUP_COLORS["open"])
         self.button_save = make_button(save, "Зберегти", self.logic.on_save, color=GROUP_COLORS["save"])
         self.button_save_as = make_button(save, "Зберегти як…", self.logic.on_save_as, color=GROUP_COLORS["save"])
         self.button_screenshot = make_button(picture, "Скрін", self.logic.on_screenshot, color=GROUP_COLORS["picture"])
         # експорт в ОС (.klc / xkb / .keylayout) — лише «Звичайна» (core/export.py)
         self.button_export = make_button(picture, "Експорт…", self.logic.on_export, color=GROUP_COLORS["picture"])
         for g in self.groups:
             buttons = g.winfo_children()
             for b in buttons:
                 b.pack(side="left", padx=(0, px(INNER_GAP)) if b is not buttons[-1] else 0)
         self.arrange(keyboard=True, export=True)

     def arrange(self, keyboard: bool, export: bool) -> None:
         """Групи в ряд з пружинами між ними; keyboard / export — чи видно «На клаву / З клави»
         і «Експорт…». Викликається на старті й при кожному перемиканні режиму."""
         if export and not self.button_export.winfo_manager():
             self.button_screenshot.pack_configure(padx=(0, px(INNER_GAP)))
             self.button_export.pack(side="left")
         elif not export and self.button_export.winfo_manager():
             self.button_export.pack_forget()
             self.button_screenshot.pack_configure(padx=0)
         frame = self.button_frame
         for g in self.groups:
             g.grid_forget()
         for col in range(2 * len(self.groups)):
             frame.columnconfigure(col, weight=0, minsize=0)
         shown = [g for g in self.groups if keyboard or g is not self.keyboard_frame]
         for i, g in enumerate(shown):
             g.grid(row=0, column=2 * i)
             if i:
                 frame.columnconfigure(2 * i - 1, weight=1, minsize=px(GROUP_GAP))

         # drop-down with a list of keyboard matrices
         # combo = ttk.Combobox(self.button_frame, values=options, state="readonly")
         # combo.set("Select your layout")
         # combo.pack(pady=20)

class LayoutBuilderApp():
    def __init__(
        self,
        root,
        statistic: dict,
        moves_config: dict,
        layout: Layout | None = None,
        on_layout_changed=None,
        geometry_name: str | None = None,
        statistic_file=None,
    ):
        self.root = root
        self.root.title("Оптимізатор розкладки")
        set_window_icon(self.root, "ukr-layout")
        self.width = 900
        self.heigh = 470
        self.root.geometry(f"{self.width}x{self.heigh}")
        # розмір вікна веде програма (_fit_window) — без «розгорнути» і
        # без розтягування мишкою; лишаються «згорнути» і «закрити»
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.toasts = Toasts(self.root)  # неблокувальні жовті сповіщення
        self._weights_gen = 0            # номер перерахунку ваг (старі результати відкидаються)

        # the real domain object -- drag/drop mutates this directly, so
        # whatever the UI shows is exactly what a headless run would score
        self.statistic = statistic
        self.statistic_file = Path(statistic_file) if statistic_file else stats_files.BUILTIN
        self._last_dir = None      # остання тека діалогів (у межах сесії)
        self.current_file = None   # файл розкладки для «Зберегти» (None — ще не збережено)
        self._mode_layouts = {}    # розкладка кожного режиму в межах сесії (перемикач не губить її)
        self._load_geometry(geometry_name or ACTIVE, moves_config)
        self.layout = (layout if layout is not None else start_layout(self.geometry_name))
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}

        self.on_layout_changed = on_layout_changed

        # --- оптимізатор живе тут, а не на рівні модуля ---
        self.processor = OptimizationProcessor(statistic, self.moves)

        # перемикач режиму — у самому верху, щоб його бачив будь-хто
        self.mode_bar = tk.Frame(self.root, bg=BG)
        self.mode_bar.pack(fill="x", padx=px(20), pady=(px(12), 0))
        tk.Label(self.mode_bar, text="Клавіатура:", bg=BG, fg=TEXT_DIM,
                 font=(FONT, 11, "bold")).pack(side="left", padx=(px(2), px(8)))
        self.mode_buttons = {}
        for name in GEOMETRIES_ORDER:
            b = make_button(self.mode_bar, GEOMETRY_TITLES.get(name, name), lambda n=name: self.on_mode(n))
            b.pack(side="left", padx=(0, px(6)))
            self.mode_buttons[name] = b
        # справа (як «⟳ з клави» на спліті): повернути дошку до ЙЦУКЕН
        self.button_ycuken = make_button(self.mode_bar, "↺ ЙЦУКЕН", self.on_ycuken, small=True)
        # і до стартової розкладки режиму (start_layout у geometry.json, для ANSI — A)
        self.button_default = make_button(self.mode_bar, "↺ За замовчуванням", self.on_default_layout,
                                          small=True)

        # tkinter / buttons
        self.status_var = tk.StringVar(value="Штраф: -")
        self.status_row = tk.Frame(self.root, bg=BG)
        self.status_row.pack(fill="x", padx=(px(22), px(20)), pady=(px(10), 0))
        # теплові мапи: затиснути — показати, поки тримаєш; клік — лишити увімкненою
        self.heat_shown = None     # що зараз на дошці: None / "freq" / "pain"
        self.heat_latched = None   # що лишається після відпускання
        self.heat_buttons = {}
        for kind, title in (("pain", "Незручність"), ("freq", "Частота")):
            b = make_button(self.status_row, title, None, small=True)
            b.pack(side="right", padx=(px(6), 0))
            for n in (1, 3):
                b.bind(f"<ButtonPress-{n}>", lambda e, k=kind: self._heat_press(k), add="+")
                b.bind(f"<ButtonRelease-{n}>", lambda e, k=kind: self._heat_release(k), add="+")
            self.heat_buttons[kind] = b
        self.status_label = tk.Label(
            self.status_row,
            textvariable=self.status_var,
            bg=BG,
            fg=TEXT,
            font=(FONT, 13, "bold"),
            anchor="w"
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        # вкладки: редактор розкладки (CYR з оптимізатора) або перегляд шару клавіатури
        self.tab_bar = tk.Frame(self.root, bg=BG)
        self.tab_bar.pack(fill="x", padx=px(20), pady=(px(8), 0))
        self.tabs = {}
        for name in ["Редактор"] + layer_view.lh.ORDER:
            b = make_button(self.tab_bar, name, lambda n=name: self.show_tab(n), small=True)
            b.pack(side="left", padx=(0, px(4)))
            self.tabs[name] = b
        # справа: скинути зміни шару / перечитати клавіатуру
        self.button_refresh_layers = make_button(self.tab_bar, "⟳ з клави", self.on_layers_refresh, small=True)
        self.button_refresh_layers.pack(side="right")
        self.button_reset_layer = make_button(self.tab_bar, "↺ скинути шар", self.on_layer_reset, small=True)
        self.button_reset_layer.pack(side="right", padx=(0, px(4)))

        # frame main
        self.board = tk.Frame(self.root, bg=PANEL, bd=0)
        self.board.pack(fill="both", expand=True, padx=px(20), pady=px(10))
        self.layer_view = layer_view.LayerView(self.root, on_change=self._layers_changed, colors=dict(
            PANEL=PANEL, SLOT=SLOT, TEXT_DIM=TEXT_DIM, KEY_TEXT=KEY_TEXT, FONT=FONT,
            FINGER={"pinky": FINGER_COLORS[Finger.PINKY], "ring": FINGER_COLORS[Finger.RING],
                    "middle": FINGER_COLORS[Finger.MIDDLE], "index": FINGER_COLORS[Finger.INDEX],
                    "thumb": FINGER_COLORS[Finger.THUMB]}))
        dump_path = layer_view.latest_dump()
        if dump_path:
            self.layer_view.set_dump(layer_view.load_dump(dump_path), f"{dump_path.name} (файл)")
        self.current_tab = "Редактор"

        # button frame
        self.button_panel = ButtonPanel(self.root, self)
        self._build_knob_panel()
        self._style_tabs()
        self.button_reset_layer.config(state="disabled")

        # layout
        self.slots = []
        self.HAND_GAP_KEYS = 4
        self.build_grid()
        self.populate_initial_keys()
        self.hovered_key = None  # Пам'ять для кнопки, на яку зараз наведено
        self._build_engine()
        # штраф — за тими ж вагами (з повзунками), що й в оптимізатора;
        # переданий ззовні дисплей рахує за сирими вагами з файлу
        if self.on_layout_changed is not None:
            self.on_layout_changed = make_score_display(self.statistic, self.moves, engine=self.engine)
        self._notify_layout_changed()
        self._apply_mode_ui()
        self._add_tooltips()
        self._center_window()

    def _add_tooltips(self):
        """Підказки до кнопок верхнього ряду, панелі повзунків і нижнього ряду."""
        p = self.button_panel
        tips = {
            self.mode_buttons.get("generic_105_alpha"):
                "Звичайна клавіатура (рядами сходинками, як на ноутбуці чи ПК).",
            self.mode_buttons.get("corne_42"): "Розділена клавіатура Corne (42 клавіші).",
            self.button_ycuken: "Поставити на дошку стандартну ЙЦУКЕН. "
                                "Спершу спитає, чи зберегти поточну розкладку.",
            self.button_default: "Повернути розкладку, з якою програма стартує (рекомендовану). "
                                 "Спершу спитає, чи зберегти поточну.",
            self.status_label: "Штраф — наскільки незручно друкувати українські тексти "
                               "цією розкладкою. Менше — краще.\n"
                               "Клавіші на дошці можна перетягувати мишкою; "
                               "права кнопка — заморозити клавішу на місці.",
            self.button_knobs: "Повзунки: що для тебе важливіше — домашній ряд, мізинці, перекати…\n"
                               "Повзунки лише перераховують штраф; щоб розкладка змінилась — Start.",
            self.button_preset: "Готові набори повзунків. Свій набір можна зберегти під назвою.",
            self.button_cpu: "Скільки процесора бере пошук (Start): частка одного ядра. "
                             "Менше — комп'ютер тихіший і не гріється, але пошук повільніший.\n"
                             "Можна міняти й під час пошуку. Запам'ятовується.",
            self.button_stats: lambda: (
                "Статистика текстів, за якою рахується штраф: які літери й пари літер "
                "трапляються найчастіше.\nВбудована — великий корпус UberText. Свою можна "
                "порахувати програмою «Статистика текстів» (ukr-stats) з власних текстів — "
                "файли з'являються тут у меню.\n"
                f"Зараз: {self._stats_title(full=True)}"),
            self.button_knobs_reset: "Усі повзунки посередині, близькість до ЙЦУКЕН вимкнена.",
            p.button_start: "Start — шукати кращу розкладку, починаючи з тієї, що на дошці. "
                            "Ще раз — зупинити.\nЗаморожені клавіші (права кнопка миші) "
                            "лишаються на місці.",
            p.button_reheat: "Під час пошуку: «струснути» оптимізатор, якщо він застряг. "
                             "Найкраще знайдене не губиться.",
            self.heat_buttons["freq"]: lambda: self._heat_tip(
                "freq", "Теплова мапа частоти: що світліша клавіша, то частіше її натискають; "
                        "на клавіші — % натискань."),
            self.heat_buttons["pain"]: lambda: self._heat_tip(
                "pain", "Теплова мапа незручності: що світліша клавіша, то більше штрафу набігає "
                        "через неї (стрибки одним пальцем, ножиці, мізинці…); на клавіші — % штрафу."),
            p.button_open: "Відкрити збережену розкладку (.json).",
            p.button_save: "Зберегти розкладку в той самий файл (вперше — спитає куди).",
            p.button_save_as: "Зберегти розкладку в новий файл.",
            p.button_screenshot: "Зберегти картинку розкладки (.png).",
            p.button_train: "Тренажер друку на розкладці, що зараз на дошці: слова з української "
                            "класики, складність — скільки літер відкрито. На звичайній клавіатурі "
                            "можна вчитись, не встановлюючи розкладку в систему.",
            p.button_export: "Файли, щоб встановити розкладку в систему: Windows (.klc для MSKLC), "
                             "Linux (xkb), macOS (.keylayout) і README, як встановити.",
            p.button_kb_write: "Записати літери з дошки на клавіатуру Corne (шар CYR).",
            p.button_kb_read: "Прочитати розкладку з клавіатури Corne на дошку.",
            self.button_refresh_layers: "Перечитати шари з клавіатури.",
            self.button_reset_layer: "Відкинути незаписані зміни цього шару.",
        }
        for name, b in self.tabs.items():
            if name == "Редактор":
                tips[b] = ("Редактор розкладки: тут літери переставляються (мишкою або Start), "
                           "тут рахується штраф.")
            else:
                how = ("лише перегляд — кирилиця редагується в «Редакторі»" if name in layer_view.READ_ONLY
                       else "клавіші можна переставляти мишкою, Shift — разом з утриманням, "
                            "права кнопка — скасувати; «На клаву» — записати")
                tips[b] = f"Шар {name} клавіатури Corne: {layer_view.lh.ABOUT.get(name, '')}\n({how})"
        for widget, text in tips.items():
            if isinstance(widget, RoundButton):
                tooltip.add(widget, lambda w=widget, t=text: self._button_tip(w, t() if callable(t) else t))
            elif widget is not None:
                tooltip.add(widget, text)

    # ------------------------------------------------------------------
    # Теплові мапи (core/heat.py): затиснути — поки тримаєш; клік — лишити
    # ------------------------------------------------------------------
    HEAT_CLICK_S = 0.35  # коротше — клік (перемикач), довше — «подивитись і відпустити»

    def _heat_values(self, kind: str) -> dict:
        if kind == "freq":
            return heat.frequency(self.layout.keys, self.statistic)
        return heat.discomfort(self.engine, self.layout.keys)

    def _show_heat(self, kind):
        """Дошка в кольорах мапи kind (None — кольори пальців)."""
        self.heat_shown = kind
        cells = heat.cells(self._heat_values(kind), kind) if kind else None
        for slot in self.slots:
            widget = slot.current_key
            if widget is not None:
                widget.heat_map = cells
                style_key(widget)
        for k, b in self.heat_buttons.items():
            on = k == self.heat_latched
            b.config(bg=ACCENT if on else BUTTON, fg=KEY_TEXT if on else TEXT,
                     activebackground=ACCENT if on else BUTTON_HOVER)

    def _heat_press(self, kind):
        if self.heat_buttons[kind].cget("state") == "disabled":
            return
        self._heat_pressed = (kind, time.monotonic())
        self._show_heat(kind)

    def _heat_release(self, kind):
        pressed = getattr(self, "_heat_pressed", None)
        self._heat_pressed = None
        if pressed is None or pressed[0] != kind:
            return
        if time.monotonic() - pressed[1] < self.HEAT_CLICK_S:   # клік — перемикач
            self.heat_latched = None if self.heat_latched == kind else kind
        self._show_heat(self.heat_latched)

    def _heat_tip(self, kind: str, text: str) -> str:
        text += ("\nЗатисни — мапа, поки тримаєш (ліва чи права кнопка миші); "
                 "клік — лишити увімкненою, ще клік — вимкнути. «Скрін» збереже те, що на дошці.")
        if self.heat_buttons[kind].cget("state") != "disabled":
            values = self._heat_values(kind)
            text += "\n\n" + heat.loads_text(self.layout.keys, values)
        return text

    def _button_tip(self, button, text: str) -> str:
        """Підказка кнопки; недоступна — ще й чому."""
        if button.cget("state") != "disabled":
            return text
        if self.processor.is_running:
            why = "іде пошук — спершу Stop"
        elif self.current_tab != "Редактор" and button not in self.tabs.values():
            why = "лише у вкладці «Редактор»"
        elif button is self.button_reset_layer:
            why = "у цьому шарі нема незаписаних змін (або шар лише для перегляду)"
        else:
            why = "не в цьому стані"
        return f"{text}\nЗараз недоступно: {why}."

    def _key_tip(self, widget) -> str:
        """Підказка клавіші на дошці: що це за клавіша і що з нею можна зробити."""
        key = widget.key
        label = widget.labels.get(key.char)
        if label is not None:
            return f"{label or 'Пробіл'} — службова клавіша, стоїть на своєму місці."
        if not key.char.strip():
            return "Порожня клавіша — літер тут нема."
        finger = {Finger.PINKY: "мізинець", Finger.RING: "безіменний", Finger.MIDDLE: "середній",
                  Finger.INDEX: "вказівний", Finger.THUMB: "великий"}[key.finger]
        hand = "лівий" if key.hand == Hand.LEFT else "правий"
        text = f"«{key.char}» — {hand} {finger}."
        extra = widget.altgr.get(key.char)
        if extra:
            text += f" З AltGr — «{extra}»."
        if key.position_id in widget.homing_ids:
            text += "\nРиска — як пухирець на F/J справжньої клавіатури: тут лежить вказівний."
        if self.processor.is_running:
            return text + "\nІде пошук — дошка заблокована, спершу Stop."
        if widget.is_frozen:
            return text + "\nЗаморожена: оптимізатор її не рухає. Права кнопка — розморозити."
        return text + ("\nПеретягни на іншу клавішу — поміняються місцями. "
                       "Права кнопка — заморозити на місці.")

    # ------------------------------------------------------------------
    # Геометрія: спліт / звичайна, перемикається в рантаймі
    # ------------------------------------------------------------------
    def _load_geometry(self, name: str, moves: dict | None = None):
        """Атрибути геометрії: позиції, розміри клавіш, ваги."""
        self.geometry_name = name
        self.geometry = geometry_config(name)
        self.positions_by_id = {p["id"]: p for p in self.geometry["positions"]}  # для ресинку при свопах
        self.base_moves = moves if moves is not None else load_moves(name)  # ваги з файлу
        self.moves = self._effective_moves()                                # + повзунки
        self.key_width = px(self.geometry["key_width"])
        self.key_height = px(self.geometry["key_height"])
        self.tolerance = px(self.geometry["tolerance_x"])
        self.stages = self.geometry["stages"]

    def _build_engine(self):
        # heavy / depends on statistic / once per geometry
        self.engine = MovementScoringEngine(self.layout.keys, self.moves)
        self.engine.prepare_statistics(self.statistic)
        # refreshing after mutation/swap
        self.engine.update_layout(self.layout.keys)

    def set_geometry(self, name: str, layout: Layout | None = None) -> bool:
        """Перемикає режим (геометрію): нова розкладка (типова для геометрії
        або передана), ваги з її moves-файлу, свіжий оптимізатор і engine,
        перебудована сітка. False — якщо оптимізація ще йде."""
        if self.processor.is_running:
            return False
        if name == self.geometry_name and layout is None:
            return True
        self._mode_layouts[self.geometry_name] = (self.layout, self.current_file)
        layout, current_file = ((layout, None) if layout is not None
                                else self._mode_layouts.get(name) or (start_layout(name), None))
        self._load_geometry(name)
        self._set_current_file(current_file)  # файл — свого режиму
        self.layout = layout
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}
        for widget in self.board.winfo_children():
            widget.destroy()
        self.slots = []
        self.build_grid()
        self.populate_initial_keys()
        self._weights_gen += 1  # перерахунок ваг попереднього режиму вже не потрібен
        self.processor = OptimizationProcessor(self.statistic, self.moves)
        self._build_engine()
        if self.on_layout_changed is not None:
            self.on_layout_changed = make_score_display(self.statistic, self.moves, engine=self.engine)
        self._build_knob_rows()
        self._notify_layout_changed()
        self._apply_mode_ui()
        self._fit_window(exact_height=True)
        return True

    def on_mode(self, name: str):
        """Кнопка перемикача режиму: міняє геометрію і запам'ятовує вибір."""
        if name == self.geometry_name:
            return
        if not self.set_geometry(name):
            self.status_var.set("Спершу зупини оптимізацію (Stop), потім перемикай клавіатуру.")
            return
        settings.save(mode=name)

    def _zmk_mode(self) -> bool:
        """Шари клавіатури й «На клаву» — лише для спліта і коли є ZMK-скрипти
        (у зібраному exe їх нема)."""
        return self.geometry_name == ZMK_GEOMETRY and ZMK_SCRIPTS.is_dir()

    def _apply_mode_ui(self):
        """Що видно в режимі: перемикач підсвічує поточний; ZMK-вкладки шарів
        і кнопки клавіатури — лише в режимі спліта."""
        for name, b in self.mode_buttons.items():
            on = name == self.geometry_name
            b.config(bg=ACCENT if on else BUTTON, fg=KEY_TEXT if on else TEXT,
                     activebackground=ACCENT if on else BUTTON_HOVER)
        if self._zmk_mode():
            if not self.tab_bar.winfo_manager():
                self.tab_bar.pack(fill="x", padx=px(20), pady=(px(8), 0), before=self.board)
        else:
            if self.current_tab != "Редактор":
                self.show_tab("Редактор")
            self.tab_bar.pack_forget()
        if self._ycuken_mode():
            if not self.button_ycuken.winfo_manager():
                self.button_ycuken.pack(side="right")
                self.button_default.pack(side="right", padx=(0, px(4)))
        else:
            self.button_ycuken.pack_forget()
            self.button_default.pack_forget()
        self.button_panel.arrange(keyboard=self._zmk_mode(), export=self._export_mode())
        self._fit_window()

    def _ycuken_mode(self) -> bool:
        """«↺ ЙЦУКЕН» — лише там, де типова розкладка геометрії і є ЙЦУКЕН
        (звичайна клавіатура; на спліті default — не ЙЦУКЕН)."""
        return self.geometry_name in YCUKEN_GEOMETRIES

    def _board_is(self, layout) -> bool:
        target = {k.position_id: k.char for k in layout.keys}
        return all(target.get(k.position_id) == k.char for k in self.layout.keys)

    def _is_ycuken(self) -> bool:
        return self._board_is(build_layout(self.geometry))

    def _reset_board(self, layout, title: str, what: str, what_acc: str | None = None) -> None:
        """Дошка -> layout (з підтвердженням), далі Start оптимізує від неї."""
        if self.processor.is_running:
            self.status_var.set(f"Спершу зупини оптимізацію (Stop), потім став {what_acc or what}.")
            return
        if self._board_is(layout):
            self.toasts.show(f"На дошці вже {what}.")
            return
        # Так — зберегти і скинути; Ні — скинути без збереження; Скасувати — нічого
        answer = messagebox.askyesnocancel(
            title, f"Зараз на дошку стане {what}.\n\nЗберегти поточну розкладку перед цим?")
        if answer is None:
            return
        if answer and not self.on_save():
            return  # збереження скасоване чи не вдалося — нічого не скидаємо
        self.set_geometry(self.geometry_name, layout=layout)
        self.toasts.show(f"На дошці {what} — Start оптимізує від неї.")

    def on_ycuken(self):
        """Дошка -> ЙЦУКЕН (`default` позицій)."""
        self._reset_board(build_layout(self.geometry), "↺ ЙЦУКЕН", "ЙЦУКЕН")

    def on_default_layout(self):
        """Дошка -> розкладка за замовчуванням (з неї режим стартує)."""
        self._reset_board(start_layout(self.geometry_name), "↺ За замовчуванням",
                          "розкладка за замовчуванням", "розкладку за замовчуванням")

    def _export_mode(self) -> bool:
        """Експорт в ОС — для геометрій, де клавіші мають фізичні назви (`key`)."""
        return any(p.get("key") for p in self.geometry["positions"])

    def _fit_window(self, exact_height: bool = False, height: int | None = None):
        """exact_height — висота рівно під вміст (після зміни режиму, щоб на
        нижчій дошці не лишалось порожнього місця від вищої).
        Вікно не менше за дошку, панель повзунків і ряд кнопок — і за
        шириною (інакше праві кнопки обрізаються), і за висотою (інакше
        обрізається нижній ряд, напр. пробіл ANSI після «Детальніше» на Corne).
        Клавіші стоять через place(), тож розмір дошки задаємо явно."""
        cells = render.key_cells(self.geometry, self.geometry_name, ui_scale())
        board_w = max(x + width for _, x, _, width in cells) + 2 * px(layer_view.BASE_X)
        board_h = max(y for _, _, y, _ in cells) + self.key_height + 2 * px(layer_view.BASE_Y)
        if self._zmk_mode():
            # вкладки шарів — на місці дошки, але вищі: під клавішами ще підпис
            # шару (не має обрізатись). Дошка редактора лишається без порожнечі,
            # вікно підлаштовується при зміні вкладки (show_tab)
            self.layer_view.config(width=board_w, height=self.layer_view.fit(max(board_w, 860)))
        self.board.config(width=board_w, height=board_h)
        self.root.update_idletasks()
        # ряд кнопок — з пружинами між групами (ButtonPanel.arrange), запас не потрібен
        buttons = self.button_panel.button_frame.winfo_reqwidth() + px(40)
        panel = self.knob_frame.winfo_reqwidth() + px(40) if getattr(self, "knobs_open", False) else 0
        # ширина — рівно під вміст: інакше після ширшого режиму (Corne -> Звичайна) вікно лишалось
        # широким, а пружини між кнопками розтягувались
        needed_w = max(px(900), board_w + px(40), buttons, panel, self.root.winfo_reqwidth())
        needed_h = max(px(450), self.root.winfo_reqheight())
        height = self.root.winfo_height() if height is None else height
        new_h = needed_h if exact_height else max(height, needed_h)
        self._resize(needed_w, new_h)

    def _resize(self, width, height):
        """Розмір вікна; лівий верхній кут лишається на місці (позицію Tk
        знає, бо на старті її задає _center_window). Якщо вікно після росту
        вилазить за екран — посуваємо назад у межі екрана."""
        self._size = (width, height)
        m = re.match(r"\d+x\d+([+-]-?\d+)([+-]-?\d+)$", self.root.geometry())
        if not m or not self.root.winfo_ismapped():
            self.root.geometry(f"{width}x{height}")
            return
        x, y = int(m.group(1)), int(m.group(2))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        nx = max(0, min(x, sw - width - 4))
        ny = max(0, min(y, sh - height - TITLE_ALLOWANCE))
        if (nx, ny) == (x, y):
            self.root.geometry(f"{width}x{height}")
        else:
            self.root.geometry(f"{width}x{height}+{nx}+{ny}")

    def _center_window(self):
        """На старті — по центру екрана (інакше WM ставить куди завгодно,
        напр. у правий верхній кут з обрізаною правою частиною)."""
        self.root.update_idletasks()
        width, height = getattr(self, "_size", (self.width, self.heigh))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, min((sh - height) // 2, sh - height - TITLE_ALLOWANCE))
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def toggle_optimization(self):
        if not self.processor.is_running:
            self.button_panel.button_start.config(text="Stop")
            self._set_file_buttons("disabled")
            self._set_keyboard_buttons("disabled")
            self._set_knobs_state("disabled")
            self.status_var.set("Оптимізую...")
            self.processor.start(
                self.layout,
                on_progress=self._on_progress,
                on_done=self._on_done,
            )
        else:
            # кнопки і score оновить _update_layout, коли воркер віддасть результат
            self.processor.stop()
            self.status_var.set("Зупиняю...")

    def _on_progress(self, layout, score, current_iteration):
        # викликається з робочого потоку -> завжди через root.after
        self.root.after(
            0,
            lambda: self.status_var.set(f"Оптимізую... ітерація {current_iteration}, штраф {score / SCORE_SCALE:.2f}")
        )

    def _update_layout(self, result_layout: Layout):
        self.layout = result_layout
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}
        self.redraw_keys()
        self.button_panel.button_start.config(text="Start")
        self._set_file_buttons("normal")
        self._set_keyboard_buttons("normal")
        self._set_knobs_state("normal")
        self._set_editor_buttons()
        self._notify_layout_changed()

    def _on_done(self, result_layout: Layout):
        update = lambda: self._update_layout(result_layout)
        self.root.after(0, update)

    def redraw_keys(self):
        """Перемальовує клавіші на дошці згідно з поточним self.layout після оптимізації."""
        for pos, slot in zip(self.geometry["positions"], self.slots):
            key = self.keys_by_position[pos["id"]]
            widget = slot.current_key
            if widget is None:
                continue
            widget.key = key
            widget.is_frozen = key.is_frozen
            style_key(widget)

    def build_grid(self):
        """Побудова сітки слотів на основі геометрії"""
        base_x, base_y = px(layer_view.BASE_X), px(layer_view.BASE_Y)  # та сама сітка, що й у вкладках шарів
        gap = px(render.GAP)  # Відстань між кнопками
        # відпущена клавіша прилипає до найближчого слота в межах усієї його
        # клітинки (з проміжками), а не лише tolerance_x від центру
        self.tolerance = max(self.tolerance, math.hypot(self.key_width + gap, self.key_height + gap) / 2)

        cells = render.key_cells(self.geometry, self.geometry_name, ui_scale())
        # ширина вікна під дошку й кнопки — _fit_window()
        for pos, x, y, width in cells:
            x, y = base_x + x, base_y + y

            # Малюємо заглушку (контур слота) для візуалізації
            tk.Frame(
                self.board,
                bg=SLOT,
                width=width,
                height=self.key_height).place(x=x, y=y)
            self.slots.append(Slot(pos, x, y, width, self.key_height))

    def populate_initial_keys(self):
        """Автоматична прив'язка літер до гріда
        Прив'язує кожен tkinter-віджет до реального доменного Key."""
        homing_ids = {p["id"] for p in self.geometry["positions"] if p.get("homing")}
        for pos, slot in zip(self.geometry["positions"], self.slots):
            key = self.keys_by_position[pos["id"]]
            #char = pos.get("default", "")
            widget = KeyLabel(self.board, relief="flat", bd=0, cursor="hand2")
            widget.place(x=slot.x, y=slot.y, width=slot.width, height=self.key_height)

            # Внутрішній стан кнопки
            widget.labels = render.MOD_LABELS.get(self.geometry_name, {})
            widget.altgr = self.geometry.get("altgr", {})
            widget.altgr_label = tk.Label(widget, font=(FONT, 10, "bold"), bd=0, padx=0, pady=0,
                                          cursor="hand2")
            widget.note_label = tk.Label(widget, font=(FONT, 8, "bold"), bd=0, padx=0, pady=0,
                                         cursor="hand2")
            widget.homing_mark = tk.Frame(widget, bd=0, highlightthickness=0, cursor="hand2")
            widget.homing_ids = homing_ids
            widget.key = key
            widget.is_frozen = key.is_frozen
            style_key(widget)
            widget.current_slot = slot
            slot.current_key = widget
            # довша пауза, ніж у кнопок: дошку часто просто розглядають
            tooltip.add(widget, lambda w=widget: self._key_tip(w), delay=1200)

            # Бінди подій / Binds
            widget.bind("<Button-1>", self.on_drag_start)
            widget.bind("<B1-Motion>", self.on_drag_motion)
            widget.bind("<ButtonRelease-1>", self.on_drag_release)
            widget.bind("<Button-3>", self.toggle_freeze)
            # мітка AltGr лежить поверх клавіші — її події віддаємо клавіші
            for sequence, handler in (("<Button-1>", self.on_drag_start), ("<B1-Motion>", self.on_drag_motion),
                                      ("<ButtonRelease-1>", self.on_drag_release),
                                      ("<Button-3>", self.toggle_freeze)):
                widget.note_label.bind(sequence, lambda e, h=handler: h(SimpleNamespace(
                    widget=e.widget.master, x_root=e.x_root, y_root=e.y_root)))
                widget.altgr_label.bind(sequence, lambda e, h=handler: h(SimpleNamespace(
                    widget=e.widget.master, x_root=e.x_root, y_root=e.y_root)))
                widget.homing_mark.bind(sequence, lambda e, h=handler: h(SimpleNamespace(
                    widget=e.widget.master, x_root=e.x_root, y_root=e.y_root)))

    def on_drag_start(self, event):
        widget = event.widget
        if widget.is_frozen or self.processor.is_running: return
        # позиція рахується від точки старту в екранних координатах:
        # winfo_x() оновлюється лише на idle і при швидкому русі відстає
        widget.start_root = (event.x_root, event.y_root)
        widget.start_pos = (widget.current_slot.x, widget.current_slot.y)
        widget.drag_pos = widget.start_pos
        widget.lift()

    def on_drag_motion(self, event):
        widget = event.widget
        if widget.is_frozen or self.processor.is_running: return

        # 1. Рухаємо перетягувану кнопку
        new_x = widget.start_pos[0] + event.x_root - widget.start_root[0]
        new_y = widget.start_pos[1] + event.y_root - widget.start_root[1]
        widget.place(x=new_x, y=new_y)
        widget.drag_pos = (new_x, new_y)

        # 2. Розраховуємо центр
        current_center_x = new_x + self.key_width / 2
        current_center_y = new_y + self.key_height / 2

        closest_slot = None
        min_distance = float('inf')

        # 3. Шукаємо найближчий слот
        for slot in self.slots:
            dist = math.hypot(current_center_x - slot.center_x, current_center_y - slot.center_y)
            if dist < min_distance:
                min_distance = dist
                closest_slot = slot

        # 4. Визначаємо цільову кнопку
        target_key = None
        if closest_slot and min_distance < self.tolerance:
            target_key = closest_slot.current_key
            # Якщо ціль — це слот, з якого ми щойно підняли кнопку, ігноруємо
            if target_key == widget:
                target_key = None

        # 5. Візуальний фідбек для цільової кнопки
        if self.hovered_key != target_key:
            # Спочатку "змиваємо" колір з попередньої підсвіченої кнопки (якщо вона була)
            if self.hovered_key and self.hovered_key.winfo_exists():
                style_key(self.hovered_key)

            # Ціль закрита перетягуваною клавішею, тож фідбек — на ній самій:
            # рамка (біла — можна, червона — ціль заморожена) і колір зони
            # пальця, куди вона потрапить
            if target_key and not target_key.is_frozen:
                style_key(target_key, DROP_OK)
                style_key(widget, DROP_OK, finger=closest_slot.finger)
            elif target_key:
                style_key(target_key, DROP_BLOCKED)
                style_key(widget, DROP_BLOCKED)
            else:
                style_key(widget)

            # Запам'ятовуємо поточну ціль
            self.hovered_key = target_key

    def on_drag_release(self, event):
        # state_hasher(self.layout, "app.on_drag_release." + a)

        widget = event.widget
        # don't allow drag release if frozen or running
        if widget.is_frozen or self.processor.is_running: return

        # Скидаємо підсвічування цільової кнопки
        if self.hovered_key and self.hovered_key.winfo_exists():
            style_key(self.hovered_key)
            self.hovered_key = None  # Очищаємо пам'ять

        drop_x, drop_y = getattr(widget, "drag_pos", (widget.current_slot.x, widget.current_slot.y))
        drop_center_x = drop_x + self.key_width / 2
        drop_center_y = drop_y + self.key_height / 2

        closest_slot = None
        min_distance = float('inf')

        for slot in self.slots:
            dist = math.hypot(
                drop_center_x - slot.center_x,
                drop_center_y - slot.center_y
            )
            if dist < min_distance:
                min_distance = dist
                closest_slot = slot

        # Логіка заміни
        if closest_slot and min_distance < self.tolerance:
            target_key = closest_slot.current_key

            if target_key and target_key.is_frozen:
                self.snap_to_slot(widget, widget.current_slot)
                style_key(widget)
                return

            original_slot = widget.current_slot


            if target_key:
                self.snap_to_slot(target_key, original_slot)

            else:
                original_slot.current_key = None

            self.snap_to_slot(widget, closest_slot)

        else:
            self.snap_to_slot(widget, widget.current_slot)

        self._sync_layout_from_ui()
        # state_hasher(self.layout, "app.on_drag_release." + a)

    def _sync_layout_from_ui(self):
        updated_keys = []
        for slot in self.slots:
            if slot.current_key is None:
                continue
            widget = slot.current_key
            if widget is not None:
                widget.key.position_id = slot.id
                self._resync_key_geometry(widget.key)
                updated_keys.append(widget.key)

        # гарантуємо, що ключі відсортовані за position_id
        sorted_keys = sorted(updated_keys, key=lambda k: k.position_id)
        self.layout.keys = sorted_keys
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}
        # палець клавіші міг змінитись разом зі слотом -> колір зони
        for slot in self.slots:
            if slot.current_key is not None:
                style_key(slot.current_key)
        self._notify_layout_changed()

    def _resync_key_geometry(self, key):
        """Оновлює геометричні поля key під його поточний position_id,
        зберігаючи char/is_frozen (доменний, а не геометричний стан)."""
        fresh = build_key_from_position(self.positions_by_id[key.position_id])
        key.x = fresh.x
        key.y = fresh.y
        key.row = fresh.row
        key.home_row = fresh.home_row
        key.col = fresh.col
        key.home_col = fresh.home_col
        key.hand = fresh.hand
        key.finger = fresh.finger
        key.base_cost = fresh.base_cost

    def snap_to_slot(self, widget, slot):
        """Жорстка прив'язка віджета до координат слота"""
        widget.place(x=slot.x, y=slot.y, width=slot.width)
        widget.current_slot = slot
        slot.current_key = widget

    def toggle_freeze(self, event):
        # early exit
        if self.processor.is_running:
            return
        widget = event.widget
        widget.is_frozen = not widget.is_frozen
        widget.key.is_frozen = widget.is_frozen
        style_key(widget)
        self._notify_layout_changed()

    def _notify_layout_changed(self):
        """Рядок стану: штраф у «Редакторі», незаписані зміни — на вкладках шарів."""
        tab = getattr(self, "current_tab", "Редактор")
        if tab != "Редактор":
            pending = self.layer_view.pending()
            here, total = len(pending.get(tab, [])), sum(len(v) for v in pending.values())
            text = f"Шар {tab}" + (f" · не записано: {here}" if here else "")
            if total > here:
                text += f" · усього не записано: {total} ({', '.join(pending)})"
            self.status_var.set(text)
        elif self.on_layout_changed:
            self.status_var.set(self.on_layout_changed(self.layout))
        if tab == "Редактор":
            self._update_knob_metrics()
            if getattr(self, "heat_shown", None):
                self._show_heat(self.heat_shown)   # розкладка змінилась — перерахувати


    # ------------------------------------------------------------------
    # Повзунки впливу (core/knobs.py): «Детальніше ▸» під клавіатурою
    # ------------------------------------------------------------------
    def _knob_state(self, name=None) -> dict:
        """{"values": {id: положення}, "closeness": bool} режиму (з settings)."""
        name = name or self.geometry_name
        state = settings.load().get("knobs", {}).get(name) or {}
        return {"values": dict(state.get("values") or {}), "closeness": bool(state.get("closeness"))}

    def _save_knob_state(self, state) -> None:
        all_states = settings.load().get("knobs") or {}
        settings.save(knobs={**all_states, self.geometry_name: state})
        self._update_preset_button()

    # --- пресети: меню «Пресет: … ▾» біля «Детальніше» ---------------
    def _custom_presets(self) -> dict:
        """Свої пресети режиму {назва: стан} (settings.json → presets)."""
        return dict((settings.load().get("presets") or {}).get(self.geometry_name) or {})

    def _save_custom_presets(self, presets: dict) -> None:
        all_presets = settings.load().get("presets") or {}
        settings.save(presets={**all_presets, self.geometry_name: presets})

    def _current_preset(self):
        return knobs.matching_preset(self._knob_state(), self.geometry_name, self._custom_presets())

    def _update_preset_button(self):
        if hasattr(self, "button_preset"):
            self.button_preset.config(text=f"Пресет: {self._current_preset() or 'свій'} ▾")

    def _update_cpu_button(self):
        self.button_cpu.config(text=f"CPU: {self.processor.cpu_percent}% ▾")

    def show_cpu_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=BUTTON, fg=TEXT, activebackground=ACCENT,
                       activeforeground=KEY_TEXT, font=(FONT, 10), bd=0)
        for percent in throttle.CHOICES:
            mark = "✓ " if percent == self.processor.cpu_percent else "    "
            note = "  (одне ядро повністю)" if percent == 100 else ""
            menu.add_command(label=f"{mark}{percent}%{note}", command=lambda p=percent: self.set_cpu(p))
        b = self.button_cpu
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def set_cpu(self, percent: int):
        """Діє одразу — і на пошук, що вже йде; запам'ятовується між запусками."""
        self.processor.set_cpu_percent(percent)
        settings.save(cpu_percent=percent)
        self._update_cpu_button()

    # ---------------------------------------------------- статистика

    def _stats_title(self, full: bool = False) -> str:
        if self.statistic_file is stats_files.BUILTIN:
            return "вбудована (UberText)" if full else "вбудована"
        stem = self.statistic_file.stem
        return str(self.statistic_file) if full else (stem if len(stem) <= 28 else stem[:27] + "…")

    def _update_stats_button(self):
        self.button_stats.config(text=f"Статистика: {self._stats_title()} ▾")

    def show_stats_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=BUTTON, fg=TEXT, activebackground=ACCENT,
                       activeforeground=KEY_TEXT, font=(FONT, 10), bd=0)
        mark = lambda on: "✓ " if on else "    "
        menu.add_command(label=f"{mark(self.statistic_file is stats_files.BUILTIN)}Вбудована — UberText, українська",
                         command=lambda: self.set_statistic(stats_files.BUILTIN))
        files = stats_files.list_files()
        if files:
            menu.add_separator()
        for path, meta in files:
            ok = meta.get("language") in stats_files.OPTIMIZER_LANGS
            label = stats_files.label(path, meta) + ("" if ok else "  (поки лише українська)")
            menu.add_command(label=f"{mark(path == self.statistic_file)}{label}",
                             state="normal" if ok else "disabled",
                             command=lambda p=path: self.set_statistic(p))
        menu.add_separator()
        menu.add_command(label="    Вибрати файл…", command=self.on_stats_pick)
        b = self.button_stats
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def on_stats_pick(self):
        folder = stats_files.stats_dir()
        path = filedialog.askopenfilename(
            parent=self.root, title="Файл статистики",
            initialdir=str(folder if folder.is_dir() else layouts_dir()),
            filetypes=[("Статистика (JSON)", "*.json"), ("Усі файли", "*")])
        if path:
            self.set_statistic(Path(path))

    def set_statistic(self, path) -> bool:
        """Інша статистика -> новий engine у фоні (як зміна ваг); вибір запам'ятовується."""
        if self.processor.is_running:
            self.status_var.set("Спершу зупини оптимізацію (Stop), потім міняй статистику.")
            return False
        if path == self.statistic_file:
            return False
        try:
            if path is stats_files.BUILTIN:
                statistic = STATISTIC
            else:
                lang = stats_files.language(path)
                if lang is not None and lang not in stats_files.OPTIMIZER_LANGS:
                    raise ValueError(f"мова файлу — {stats_files.LANG_NAMES.get(lang, lang)}; "
                                     "оптимізатор поки працює лише з українською")
                statistic = stats_files.load(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Статистика", f"Не вдалося відкрити статистику:\n{error}")
            return False
        self.statistic, self.statistic_file = statistic, path
        settings.save(statistic_file=None if path is stats_files.BUILTIN else str(path))
        self._update_stats_button()
        self._rebuild_weights(f"статистика «{self._stats_title()}»", head="Статистику змінено")
        return True

    def show_preset_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=BUTTON, fg=TEXT, activebackground=ACCENT,
                       activeforeground=KEY_TEXT, font=(FONT, 10), bd=0)
        current = self._current_preset()
        custom = self._custom_presets()

        def item(title, state):
            mark = "✓ " if title == current else "    "
            menu.add_command(label=mark + title, command=lambda: self.apply_preset(title, state))
        for p in knobs.presets_for(self.geometry_name):
            item(p.title, p.state())
        if custom:
            menu.add_separator()
            for name, state in custom.items():
                item(name, state)
        menu.add_separator()
        menu.add_command(label="    Зберегти пресет…", command=self.on_preset_save)
        if current in custom:
            menu.add_command(label=f"    Видалити «{current}»", command=lambda: self.on_preset_delete(current))
        b = self.button_preset
        menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def apply_preset(self, title: str, state: dict):
        if self.processor.is_running:
            self.status_var.set("Спершу зупини оптимізацію (Stop), потім міняй пресет.")
            return
        old = self._knob_state()
        new = {"values": dict(state.get("values") or {}), "closeness": bool(state.get("closeness"))}
        self._save_knob_state(new)
        self._build_knob_rows()
        if knobs.state_key(old, self.geometry_name) != knobs.state_key(new, self.geometry_name):
            self._rebuild_weights(f"пресет «{title}»")
        if new["closeness"] and self._ycuken_mode() and not self._is_ycuken():
            self.toasts.show("Щоб стартувати саме від ЙЦУКЕН — «↺ ЙЦУКЕН» вгорі справа.")

    def on_preset_save(self):
        name = simpledialog.askstring("Зберегти пресет", "Назва пресету:", parent=self.root)
        name = (name or "").strip()
        if not name:
            return
        if name in {p.title for p in knobs.PRESETS} or name == "свій":
            self.toasts.show(f"«{name}» — уже вбудований пресет, обери іншу назву.")
            return
        custom = self._custom_presets()
        if name in custom and not messagebox.askyesno("Зберегти пресет", f"Замінити пресет «{name}»?"):
            return
        custom[name] = self._knob_state()
        self._save_custom_presets(custom)
        self._update_preset_button()
        self.toasts.show(f"Пресет «{name}» збережено.")

    def on_preset_delete(self, name: str):
        custom = self._custom_presets()
        if custom.pop(name, None) is not None:
            self._save_custom_presets(custom)
            self._update_preset_button()
            self.toasts.show(f"Пресет «{name}» видалено (повзунки лишились як були).")

    def _effective_moves(self) -> dict:
        state = self._knob_state()
        return knobs.apply(self.base_moves, state["values"], self.geometry, state["closeness"])

    def _build_knob_panel(self):
        self.knobs_open = False
        self.knob_bar = tk.Frame(self.root, bg=BG)
        self.knob_bar.pack(fill="x", padx=px(20), pady=(0, px(6)), before=self.button_panel.button_frame)
        self.button_knobs = make_button(self.knob_bar, "Детальніше ▸", self.toggle_knobs, small=True)
        self.button_knobs.pack(side="left")
        self.button_preset = make_button(self.knob_bar, "Пресет: ▾", self.show_preset_menu, small=True)
        self.button_preset.pack(side="left", padx=(px(8), 0))
        self.button_cpu = make_button(self.knob_bar, "", self.show_cpu_menu, small=True)
        self.button_cpu.pack(side="left", padx=(px(8), 0))
        self._update_cpu_button()
        self.button_stats = make_button(self.knob_bar, "", self.show_stats_menu, small=True)
        self.button_stats.pack(side="left", padx=(px(8), 0))
        self._update_stats_button()
        self.button_knobs_reset = make_button(self.knob_bar, "Скинути до рекомендованих",
                                              self.on_knobs_reset, small=True)
        self.knob_frame = tk.Frame(self.root, bg=PANEL)
        self.knob_rows = {}
        self._build_knob_rows()

    def _build_knob_rows(self):
        """Рядки повзунків поточного режиму (близькість — лише «Звичайна»)."""
        if not hasattr(self, "knob_frame"):
            return
        for widget in self.knob_frame.winfo_children():
            widget.destroy()
        self.knob_rows = {}
        state = self._knob_state()
        self.closeness_var = tk.BooleanVar(value=state["closeness"])
        label_opts = dict(bg=PANEL, font=(FONT, 10, "bold"))
        for row, knob in enumerate(knobs.knobs_for(self.geometry_name)):
            # назва, під нею дрібно — цифра, на яку повзунок впливає
            cell = tk.Frame(self.knob_frame, bg=PANEL)
            cell.grid(row=row, column=0, sticky="w", padx=(px(12), px(10)), pady=(px(4), px(2)))
            if knob.id == "closeness":
                title = tk.Checkbutton(cell, text=knob.title, variable=self.closeness_var,
                                       command=self.on_closeness_toggle, fg=TEXT, selectcolor=SLOT,
                                       activebackground=PANEL, activeforeground=TEXT, bd=0,
                                       highlightthickness=0, **label_opts)
            else:
                title = tk.Label(cell, text=knob.title, fg=TEXT, **label_opts)
            title.pack(anchor="w")
            tip = KNOB_TIPS.get(knob.id, "")
            tooltip.add(title, tip)
            metric = tk.Label(cell, fg=TEXT_DIM, anchor="w", bg=PANEL, font=(FONT, 9))
            metric.pack(anchor="w")
            tooltip.add(metric, "Як зараз у розкладці на дошці (за текстами корпусу).")
            left = tk.Label(self.knob_frame, text=knob.left, fg=TEXT_DIM, **label_opts)
            left.grid(row=row, column=1, sticky="e")
            scale = tk.Scale(self.knob_frame, from_=-knobs.LIMIT, to=knobs.LIMIT, resolution=0.05,
                             orient="horizontal", showvalue=0, length=px(220), sliderlength=px(18), width=px(12),
                             bg=PANEL, fg=TEXT, troughcolor=SLOT, activebackground=ACCENT,
                             highlightthickness=0, bd=0,
                             command=lambda _v, k=knob.id: self._on_knob_move(k))
            scale.set(state["values"].get(knob.id, 0.0))
            scale.grid(row=row, column=2, padx=px(6))
            scale.bind("<ButtonRelease-1>", lambda _e, k=knob.id: self.on_knob_release(k))
            right = tk.Label(self.knob_frame, text=knob.right, fg=TEXT_DIM, **label_opts)
            right.grid(row=row, column=3, sticky="w")
            step_label = tk.Label(self.knob_frame, fg=ACCENT, width=14, anchor="w", **label_opts)
            step_label.grid(row=row, column=4, sticky="w", padx=(px(10), px(12)))
            for widget in (left, right):
                tooltip.add(widget, tip)
            tooltip.add(scale, lambda t=tip, k=knob.id: self._knob_scale_tip(t, k))
            tooltip.add(step_label, "Наскільки змінено вагу проти рекомендованої (посередині — як є).")
            self.knob_rows[knob.id] = SimpleNamespace(scale=scale, step=step_label, metric=metric)
            self._on_knob_move(knob.id)
        self._set_knobs_state("disabled" if self.processor.is_running else "normal")
        self._update_knob_metrics()
        self._update_preset_button()

    def _knob_scale_tip(self, tip: str, knob_id: str) -> str:
        text = tip + "\nТягни мишкою; штраф перерахується, коли відпустиш."
        if self.processor.is_running:
            return text + "\nЗараз недоступно: іде пошук — спершу Stop."
        if knob_id == "closeness" and not self.closeness_var.get():
            return text + "\nЗараз недоступно: спершу постав галочку ліворуч."
        return text

    def toggle_knobs(self):
        self.knobs_open = not self.knobs_open
        if self.knobs_open:
            self.knob_frame.pack(fill="x", padx=px(20), pady=(0, px(8)), before=self.button_panel.button_frame)
            self.button_knobs_reset.pack(side="right")
            self.button_knobs.config(text="Детальніше ▾")
            self._update_knob_metrics()
        else:
            self.knob_frame.pack_forget()
            self.button_knobs_reset.pack_forget()
            self.button_knobs.config(text="Детальніше ▸")
        # вікно росте/зменшується на висоту панелі, щоб клавіатуру не стискало
        self.root.update_idletasks()
        extra = self.knob_frame.winfo_reqheight() + 8
        height = self.root.winfo_height()
        if self.knobs_open:
            height = max(height, self.heigh) + extra
        else:
            height = max(self.heigh, height - extra)
        self._fit_window(height=height)

    def _set_knobs_state(self, state):
        for row in getattr(self, "knob_rows", {}).values():
            disabled = state == "disabled" or (row is self.knob_rows.get("closeness")
                                               and not self.closeness_var.get())
            row.scale.config(state="disabled" if disabled else "normal")

    def _knob_values(self) -> dict:
        return {k: round(float(r.scale.get()), 2) for k, r in self.knob_rows.items()}

    def _on_knob_move(self, knob_id):
        """Плавний рух: лише підпис кроку; перерахунок — на відпусканні."""
        row = self.knob_rows.get(knob_id)
        if row is not None:
            row.step.config(text=knobs.STEP_TITLES[knobs.step(row.scale.get())])

    def on_knob_release(self, knob_id):
        if self.processor.is_running:
            return
        old = self._knob_state()
        values = self._knob_values()
        self._save_knob_state({"values": values, "closeness": old["closeness"]})
        if knobs.step(old["values"].get(knob_id, 0.0)) != knobs.step(values[knob_id]):
            knob = knobs.KNOBS_BY_ID[knob_id]
            self._rebuild_weights(f"{knob.title}: {knobs.STEP_TITLES[knobs.step(values[knob_id])]}")

    def on_closeness_toggle(self):
        if self.processor.is_running:
            self.closeness_var.set(not self.closeness_var.get())
            return
        on = self.closeness_var.get()
        self._save_knob_state({"values": self._knob_values(), "closeness": on})
        self._set_knobs_state("normal")
        self._rebuild_weights("Близькість до ЙЦУКЕН: " + ("увімкнено" if on else "вимкнено"))

    def on_knobs_reset(self):
        if self.processor.is_running:
            return
        old = self._knob_state()
        changed = old["closeness"] or any(knobs.step(v) for v in old["values"].values())
        self._save_knob_state({"values": {}, "closeness": False})
        self._build_knob_rows()
        if changed:
            self._rebuild_weights("Ваги — рекомендовані")

    def _rebuild_weights(self, what: str, head: str = "Ваги змінено"):
        """Нові ваги -> новий engine (prepare_statistics ~2 с) у фоні. Розкладка
        не змінюється — лише штраф; юзер сам тисне Start. Нічого не блокує."""
        self._weights_gen += 1
        gen, name = self._weights_gen, self.geometry_name
        moves = self._effective_moves()
        snapshot = [copy.copy(k) for k in self.layout.keys]
        self.button_panel.button_start.config(state="disabled")
        self.status_var.set("Перераховую штраф за новими вагами…")

        result = {}

        def work():  # без tkinter: з фонового потоку його чіпати не можна
            engine = MovementScoringEngine(snapshot, moves)
            engine.prepare_statistics(self.statistic)
            result["engine"] = engine

        def poll():
            if "engine" not in result:
                self.root.after(100, poll)
                return
            done(result["engine"])

        def done(engine):
            if gen != self._weights_gen or name != self.geometry_name:
                return  # прийшли новіші ваги або інший режим
            self.moves, self.engine = moves, engine
            self.processor = OptimizationProcessor(self.statistic, moves)
            if self.on_layout_changed is not None:
                self.on_layout_changed = make_score_display(self.statistic, moves, engine=engine)
            self._set_editor_buttons()
            self._notify_layout_changed()
            self.toasts.show(f"{head} — {what}.\n"
                             f"Штраф поточної розкладки: {self._current_score():.2f}. "
                             "Натисни Start, щоб підлаштувати розкладку.")

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, poll)

    def _update_knob_metrics(self):
        """Цифри біля повзунків (лише коли панель відкрита — метрики не безкоштовні)."""
        if not getattr(self, "knobs_open", False) or not self.knob_rows:
            return
        m = layout_metrics(self.layout.keys, self.statistic)
        text = {
            "home_row": f"зараз {m['home_row']:.0f}% натискань",
            "vertical": f"зараз {m['sfb']:.1f}% пар літер одним пальцем",
            "pinky": f"зараз лівий {m['pinky_left']:.1f}% · правий {m['pinky_right']:.1f}%",
            "alternation": f"зараз чергування {m['alternation']:.0f}% · перекати {m['rolls']:.0f}%",
        }
        if "closeness" in self.knob_rows:
            c = knobs.closeness_metrics(self.layout.keys, self.geometry, self.statistic)
            text["closeness"] = f"на своїх місцях {c['in_place']} з {c['of']} ({c['share']:.0f}% тексту)"
        for knob_id, row in self.knob_rows.items():
            row.metric.config(text=text.get(knob_id, ""))

    # ------------------------------------------------------------------
    # Файли розкладки: «Відкрити…», «Зберегти», «Зберегти як…»
    # ------------------------------------------------------------------
    def _set_file_buttons(self, state):
        panel = self.button_panel
        for b in (panel.button_open, panel.button_save, panel.button_save_as, panel.button_screenshot,
                  panel.button_export, panel.button_train, *getattr(self, "heat_buttons", {}).values()):
            b.config(state=state)
        if state == "disabled" and getattr(self, "heat_shown", None):
            self.heat_latched = None   # пошук / вкладка шару — мапу знімаємо
            self._show_heat(None)

    def _dialog_dir(self):
        return str(self._last_dir or layouts_dir())

    def _set_current_file(self, path):
        self.current_file = Path(path) if path else None
        self._last_dir = self.current_file.parent if self.current_file else self._last_dir
        name = f" — {self.current_file.name}" if self.current_file else ""
        self.root.title(f"Оптимізатор розкладки{name}")

    def on_save(self):
        """Перезаписує відкритий/збережений файл; якщо його ще нема — як «Зберегти як…»."""
        if self.processor.is_running:
            return False
        if self.current_file is None:
            return self.on_save_as()
        return self._save_to(self.current_file)

    def on_save_as(self) -> bool:
        """True — збережено; False — скасовано діалог або помилка."""
        if self.processor.is_running:
            return False
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Зберегти розкладку",
            initialdir=self._dialog_dir(), initialfile=f"layout_{self.geometry_name}_{stamp}.json",
            defaultextension=".json", filetypes=[("Розкладка (JSON)", "*.json")])
        return bool(path) and self._save_to(path)

    def _save_to(self, path) -> bool:
        try:
            saved = self.processor.layout_save(self.layout, path)
        except OSError as error:
            messagebox.showerror("Зберегти", f"Не вдалося зберегти:\n{error}")
            return False
        self._set_current_file(saved)
        self.status_var.set(f"Збережено: {saved}")
        self.toasts.show(f"Збережено: {saved}")
        return True

    def on_open(self):
        if self.processor.is_running:
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Відкрити розкладку", initialdir=self._dialog_dir(),
            filetypes=[("Розкладка (JSON)", "*.json"), ("Усі файли", "*")])
        if not path:
            return
        try:
            data = self.processor.layout_load(path)
            problem = self.layout_file_problem(data)
        except (OSError, ValueError, KeyError, TypeError) as error:
            problem = f"файл не читається як розкладка: {error}"
        if problem:
            messagebox.showerror("Відкрити", f"{Path(path).name}: {problem}")
            return
        self._apply_recorded_state(data)
        self._set_current_file(path)
        self.status_var.set(f"Відкрито: {path} · {self.status_var.get()}")

    def layout_file_problem(self, data) -> str | None:
        """Чи підходить файл до поточного режиму: ті самі позиції й той самий
        набір літер (інакше — розкладка іншої клавіатури або зіпсований файл)."""
        if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
            return "очікується список клавіш"
        ids = {k.position_id for k in self.layout.keys}
        file_ids = {d["position_id"] for d in data}
        if not file_ids <= ids:
            return (f"це розкладка для іншої клавіатури (режим зараз — "
                    f"{GEOMETRY_TITLES.get(self.geometry_name, self.geometry_name)})")
        letters = lambda chars: sorted(c for c in chars if len(c) == 1)
        here = letters(k.char for k in self.layout.keys if k.position_id in file_ids)
        there = letters(d["char"] for d in data)
        if here != there:
            return "набір символів не збігається з поточним режимом"
        return None

    def _apply_recorded_state(self, data: list[dict]):
        state_by_position = {
            p["position_id"]: (p["char"], p["is_frozen"]) for p in data
        }
        print("recorded ids:", sorted(state_by_position.keys()))
        print("layout ids:", sorted(k.position_id for k in self.layout.keys))
        # rewrite the layout
        for key in self.layout.keys:
            if key.position_id in state_by_position:
                char, is_frozen = state_by_position[key.position_id]
                key.char = char
                key.is_frozen = is_frozen
        # rebuild the layout UI matrix
        for slot in self.slots:
            widget = slot.current_key
            if widget is None:
                continue
            key = widget.key
            widget.is_frozen = key.is_frozen
            style_key(widget)
        print("post-recall chars:", {k.position_id: (k.char, k.is_frozen) for k in self.layout.keys})
        self._notify_layout_changed()

    # ------------------------------------------------------------------
    # Tabs: editor / read-only keyboard layers
    # ------------------------------------------------------------------
    def _style_tabs(self):
        pending = self.layer_view.pending()
        for name, b in self.tabs.items():
            on = name == self.current_tab
            color = layer_view.LAYER_COLORS.get(name, ACCENT)
            b.config(bg=color if on else BUTTON, fg=KEY_TEXT if on else TEXT,
                     activebackground=color if on else BUTTON_HOVER,
                     text=name + (" •" if name in pending else ""))

    def _layers_changed(self):
        if hasattr(self, "button_panel"):
            self._style_tabs()
            self._notify_layout_changed()

    def _set_editor_buttons(self):
        """Start/Reheat/Rec — лише для розкладки в «Редакторі»."""
        if self.processor.is_running:
            return
        state = "normal" if self.current_tab == "Редактор" else "disabled"
        for b in (self.button_panel.button_start, self.button_panel.button_reheat):
            b.config(state=state)
        self._set_file_buttons(state)
        self.button_reset_layer.config(state="normal" if self.layer_view.editable(self.current_tab)
                                       and self.current_tab != "Редактор" else "disabled")

    def on_layer_reset(self):
        if self.current_tab != "Редактор" and self.layer_view.pending().get(self.current_tab):
            self.layer_view.reset_layer(self.current_tab)

    def _confirm_discard(self):
        pending = self.layer_view.pending()
        if not pending:
            return True
        n = sum(len(v) for v in pending.values())
        return messagebox.askyesno("Незаписані зміни",
                                   f"Відкинути незаписані зміни ({n} клавіш у {', '.join(pending)})?")

    def show_tab(self, name):
        if name == "Редактор":
            self.layer_view.pack_forget()
            # над «Детальніше ▸» (knob_bar), а не просто над кнопками —
            # інакше після зміни вкладки панель повзунків стрибала вгору
            self.board.pack(fill="both", expand=True, padx=px(20), pady=px(10),
                            before=self.knob_bar)
        else:
            self.board.pack_forget()
            self.layer_view.pack(fill="both", expand=True, padx=px(20), pady=px(10),
                                 before=self.knob_bar)
            self.layer_view.show(name)
        previous, self.current_tab = self.current_tab, name
        self._style_tabs()
        self._set_editor_buttons()
        self._notify_layout_changed()
        if (previous == "Редактор") != (name == "Редактор"):
            self._fit_window(exact_height=True)  # дошка і шари — різної висоти

    def _set_layers_dump(self, dump, source):
        self.layer_view.set_dump(dump, source)
        if self.current_tab != "Редактор":
            self.layer_view.show(self.current_tab)
        self._fit_window()  # інше джерело / шари — підпис може стати довшим

    def on_layers_refresh(self):
        if not self._confirm_discard():
            return
        ks = self._keyboard_sync()

        def done(dump):
            self._set_keyboard_buttons("normal")
            self._notify_layout_changed()
            self._set_layers_dump(dump, f"клавіатура, {self._now()}")
        self._keyboard_task("Читаю клавіатуру...", ks.read_dump, done)

    @staticmethod
    def _now():
        from datetime import datetime
        return datetime.now().strftime("%H:%M")

    # ------------------------------------------------------------------
    # Keyboard: write the layout to the CYR layer / read it back
    # ------------------------------------------------------------------
    def _set_keyboard_buttons(self, state):
        self.button_panel.button_kb_write.config(state=state)
        self.button_panel.button_kb_read.config(state=state)
        self.button_refresh_layers.config(state=state)

    def _layout_items(self):
        return [{"position_id": k.position_id, "char": k.char, "is_frozen": k.is_frozen}
                for k in self.layout.keys]

    def _current_score(self):
        self.engine.update_layout(self.layout.keys)
        return self.engine.score().total_penalty / SCORE_SCALE

    def _keyboard_task(self, status, work, done):
        """work() — у фоновому потоці (порт, inkscape), done(result) — в UI-потоці."""
        if self.processor.is_running:
            return
        self._set_keyboard_buttons("disabled")
        self.status_var.set(status)

        def run():
            try:
                result = work()
            except Exception as e:  # noqa: BLE001 — показати автору будь-яку помилку
                self.root.after(0, lambda e=e: self._keyboard_failed(e))
                return
            self.root.after(0, lambda: done(result))
        threading.Thread(target=run, daemon=True).start()

    def _keyboard_failed(self, error):
        self._set_keyboard_buttons("normal")
        self._notify_layout_changed()
        messagebox.showerror("Клавіатура", f"{type(error).__name__}: {error}")

    @staticmethod
    def _keyboard_sync():
        if str(ZMK_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(ZMK_SCRIPTS))
        import keyboard_sync
        return keyboard_sync

    def on_keyboard_write(self):
        if self.current_tab != "Редактор":
            return self.on_layers_write()
        items = self._layout_items()
        score = self._current_score()
        ks = self._keyboard_sync()
        self._keyboard_task("Читаю клавіатуру...", lambda: ks.prepare(items),
                            lambda plan: self._confirm_keyboard_write(ks, plan, items, score))

    def _confirm_keyboard_write(self, ks, plan, items, score):
        if not plan.changes:
            self._set_keyboard_buttons("normal")
            self._notify_layout_changed()
            self.toasts.show("Клавіатура вже збігається з розкладкою на екрані.")
            return
        question = (f"Записати {len(plan.changes)} клавіш у шар CYR ({plan.port})?\n\n"
                    f"{plan.diff_text}\n\nШтраф розкладки: {score:.2f}")
        if not messagebox.askyesno("На клаву", question):
            self._set_keyboard_buttons("normal")
            self._notify_layout_changed()
            return
        self._keyboard_task("Записую на клавіатуру...", lambda: ks.apply(plan, items, score),
                            lambda out: self._keyboard_written(plan, out))

    def _keyboard_written(self, plan, out):
        self._set_keyboard_buttons("normal")
        cyr = next(l for l in plan.target["layers"] if l["name"] == "CYR")["bindings"]
        self.layer_view.sync_layer("CYR", cyr)  # незаписані зміни інших шарів лишаються
        self._notify_layout_changed()
        root = Path(__file__).resolve().parents[1]
        rel = lambda p: str(p.relative_to(root)) if root in p.parents else str(p)  # noqa: E731
        lines = [f"Записано {len(plan.changes)} клавіш у CYR.", "",
                 f"відкат: {rel(out['before'])}", f"розкладка: {rel(out['layout'])}"]
        lines += [f"{k}: {rel(out[k])}" for k in ("png", "svg", "html") if k in out]
        self.status_var.set(self.status_var.get() + f"   · на клаві з {plan.stamp[-4:-2]}:{plan.stamp[-2:]}")
        self.toasts.show("\n".join(lines), ms=12000)

    def on_layers_write(self):
        if not self.layer_view.pending():
            self.toasts.show("Незаписаних змін у шарах немає.")
            return
        ks = self._keyboard_sync()
        working, base = self.layer_view.dump, self.layer_view.base
        self._keyboard_task("Читаю клавіатуру...", lambda: ks.prepare_layers(working, base),
                            lambda plan: self._confirm_layers_write(ks, plan))

    def _confirm_layers_write(self, ks, plan):
        self._set_keyboard_buttons("normal")
        self._notify_layout_changed()
        if not plan.count:
            self.toasts.show("Клавіатура вже має ці зміни.")
            return
        warn = ""
        if plan.conflicts:
            where = ", ".join(f"{n}[{p}]" for n, p in plan.conflicts)
            warn = (f"\n\nУВАГА: на клавіатурі ці клавіші вже не такі, як при читанні: {where}. "
                    "Запис їх перезапише.")
        question = (f"Записати {plan.count} клавіш у {', '.join(plan.changes)} ({plan.port})?\n\n"
                    f"{plan.diff_text}{warn}")
        if not messagebox.askyesno("На клаву", question):
            return
        self._keyboard_task("Записую на клавіатуру...", lambda: ks.apply_layers(plan),
                            lambda out: self._layers_written(plan, out))

    def _layers_written(self, plan, out):
        self._set_keyboard_buttons("normal")
        self._set_layers_dump(out["dump"], f"{out['written'].name} (щойно записано)")
        root = Path(__file__).resolve().parents[1]
        rel = lambda p: str(p.relative_to(root)) if root in p.parents else str(p)  # noqa: E731
        self.toasts.show("\n".join([
            f"Записано {plan.count} клавіш у {', '.join(plan.changes)}.",
            f"відкат: {rel(out['before'])}", f"html: {rel(out['html'])}"]), ms=12000)

    def on_keyboard_read(self):
        if not self._confirm_discard():
            return
        ks = self._keyboard_sync()
        self._keyboard_task("Читаю клавіатуру...", ks.read_dump, self._keyboard_loaded)

    def _keyboard_loaded(self, dump):
        self._set_keyboard_buttons("normal")
        self._set_layers_dump(dump, f"клавіатура, {self._now()}")
        items = self._keyboard_sync().cfl.extract(dump)
        # тхамби/порожні кути на клавіатурі не мають літер — лишаємо, як на екрані
        frozen = {k.position_id: k.is_frozen for k in self.layout.keys}
        data = [{"position_id": d["position_id"], "char": d["char"],
                 "is_frozen": frozen.get(d["position_id"], False)}
                for d in items if d["char"]]
        incoming = {d["char"] for d in data}
        clash = [k.char for k in self.layout.keys
                 if k.char and k.char in incoming
                 and k.position_id not in {d["position_id"] for d in data}]
        if clash:
            messagebox.showerror("З клави", f"літери з клавіатури дублюють клавіші поза шаром: {clash}")
            self._notify_layout_changed()
            return
        self._apply_recorded_state(data)

    # ------------------------------------------------------------------
    # Record the layout into different formats
    # ------------------------------------------------------------------
    def screenshot_name(self):
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        return f"layout_{self.geometry_name}_{stamp}.png"

    def save_screenshot(self, path):
        """Картинка поточної розкладки «Редактора» (PNG або SVG за розширенням)."""
        title, subtitle = render.default_title(self.geometry_name, self._current_score())
        cells, footer = None, ""
        if self.heat_shown:
            values = self._heat_values(self.heat_shown)
            cells, footer = heat.cells(values, self.heat_shown), heat.loads_text(self.layout.keys, values)
            title += " · " + HEAT_TITLES[self.heat_shown]
        return render.save(self.layout.keys, self.geometry, self.geometry_name, path, title, subtitle,
                           heat=cells, footer=footer)

    def on_screenshot(self):
        initial_dir = self._dialog_dir()
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Зберегти картинку розкладки",
            initialdir=str(initial_dir), initialfile=self.screenshot_name(), defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("SVG", "*.svg")])
        if not path:
            return
        try:
            saved = self.save_screenshot(path)
        except OSError as error:
            messagebox.showerror("Скрін", f"Не вдалося зберегти: {error}")
            return
        self._last_dir = saved.parent
        self.status_var.set(f"Картинка: {saved}")
        self.toasts.show(f"Картинка: {saved}")

    def on_train(self):
        """Вікно «Тренування» з розкладкою, що зараз на дошці (знімок; модальне)."""
        if self.processor.is_running:
            return
        from uiux.trainer import TrainerWindow
        # найдорожчі для цієї розкладки бі/триграми — режим «Поєднання»
        self.engine.update_layout(self.layout.keys)
        hard = self.engine.ngram_penalty("bigrams") + self.engine.ngram_penalty("trigrams")
        return TrainerWindow(self.root, self.layout.keys, self.geometry, self.geometry_name,
                             self.statistic, sorted(hard, key=lambda x: -x[1]))

    def on_export(self):
        """Файли розкладки для Windows / Linux / macOS + README у вибрану теку
        (підтека ukr-layout_<дата_час>)."""
        if self.processor.is_running or not self._export_mode():
            return
        base = filedialog.askdirectory(parent=self.root, title="Куди покласти файли розкладки",
                                       initialdir=self._dialog_dir(), mustexist=True)
        if not base:
            return
        out = Path(base) / f"ukr-layout_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
        try:
            export.export_all(export.chars_from_keys(self.layout.keys), self.geometry, out)
        except (OSError, ValueError) as error:
            messagebox.showerror("Експорт", f"Не вдалося експортувати:\n{error}")
            return
        self._last_dir = Path(base)
        self.status_var.set(f"Експорт: {out}")
        self.toasts.show(f"Розкладку експортовано: {out}\n"
                         "Windows — .klc (MSKLC), Linux — .xkb, macOS — .keylayout;\n"
                         "як встановити — README.txt там же.", ms=12000)


def _windows_setup():
    """Windows: чіткий текст на екранах з масштабом 125–200% (інакше Tk
    розмиває вікно) і знижений пріоритет процесу — оптимізація не гальмує
    решту системи."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass


def startup_statistic():
    """Запам'ятована статистика (settings "statistic_file"), якщо файл є і мова
    українська; інакше — вбудована. -> (statistic, файл або None)."""
    chosen = settings.load().get("statistic_file")
    if chosen:
        try:
            if stats_files.language(chosen) in stats_files.OPTIMIZER_LANGS:
                return stats_files.load(chosen), Path(chosen)
        except (OSError, ValueError):
            pass
    return STATISTIC, stats_files.BUILTIN


def main(smoke_ms: int | None = None):
    """Запуск GUI. smoke_ms — закрити вікно через стільки мс (перевірка
    зібраного exe в CI: вікно будується повністю і процес виходить з кодом 0)."""
    _windows_setup()
    statistic, statistic_file = startup_statistic()
    mode = settings.initial_mode(GEOMETRIES)  # запам'ятований режим; в exe типово «Звичайна»
    moves_config = load_moves(mode)
    root = tk.Tk()
    init_ui_scale(root)          # до побудови вікон: розміри в px — під масштаб екрана
    # головне вікно будується сховане, поверх — інвітейшн (uiux/invite.py): старт без мигання
    root.withdraw()
    from uiux.invite import Invite, next_launch
    invite = Invite(root, next_launch())
    app = LayoutBuilderApp(
        root,
        statistic=statistic,
        moves_config=moves_config,
        on_layout_changed=make_score_display(statistic, moves_config),
        geometry_name=mode,
        statistic_file=statistic_file)
    root.update_idletasks()

    def show():
        root.deiconify()
        invite.lift()            # інвітейшн лишається зверху, доки не клацнуть
    root.after(150, show)
    if smoke_ms:
        root.after(smoke_ms, root.destroy)
    root.mainloop()
    return app


if __name__ == "__main__":
    main()
