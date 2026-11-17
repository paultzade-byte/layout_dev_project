
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import math
import sys
import threading
from types import SimpleNamespace
import copy

from config.main_config import (MOVES_CONFIG, STATISTIC, ACTIVE, GEOMETRIES, GEOMETRY_TITLES, geometry_config,
                                load_moves, start_layout)
from config import settings
from core.layout_factory import build_layout, build_key_from_position
from core.models import Finger, Layout, Key
from core.scorer import MovementScoringEngine
from uiux.processors import OptimizationProcessor
from uiux import layer_view
from uiux.widgets import RoundButton
from uiux import render
from uiux.toast import Toasts
from core import knobs
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
    KEY_FONT, KEY_TEXT, PANEL, SLOT, TEXT, TEXT_DIM,
)


def style_key(widget, border: str | None = None, finger: Finger | None = None) -> None:
    """Єдине місце, де задається вигляд клавіші. Під час перетягування:
    border — рамка (DROP_OK / DROP_BLOCKED), finger — зона пальця, в яку
    клавіша потрапить (попередній перегляд кольору)."""
    key = widget.key
    if widget.is_frozen:
        bg, fg = FROZEN_BG, FROZEN_FG
    else:
        bg, fg = FINGER_COLORS.get(finger or key.finger, TEXT_DIM), KEY_TEXT
    border = border or (FROZEN_FG if widget.is_frozen else bg)
    # службові клавіші (Shft, SPA...) — підписи як на картинці (render.MOD_LABELS)
    text = getattr(widget, "labels", {}).get(key.char, key.char)
    font = KEY_FONT if len(text) <= 2 else (FONT, 11, "bold")
    widget.config(
        text=text, bg=bg, fg=fg, font=font,
        highlightthickness=2, highlightbackground=border, highlightcolor=border,
    )
    # AltGr-символ клавіші (geometry["altgr"]: літера -> символ) — дрібно в
    # правому верхньому куті, як на картинці; іде за літерою при перетягуванні
    mark = getattr(widget, "altgr_label", None)
    if mark is not None:
        extra = "" if widget.is_frozen else getattr(widget, "altgr", {}).get(key.char, "")
        if extra:
            mark.config(text=extra, bg=bg, fg=fg)
            mark.place(relx=1.0, x=-5, y=2, anchor="ne")
        else:
            mark.place_forget()


def make_button(parent, text, command, small=False):
    """Кнопка апки: заокруглена (uiux.widgets.RoundButton), hover — сама."""
    return RoundButton(
        parent, text=text, command=command, font=(FONT, 9 if small else 11, "bold"),
        bg=BUTTON, fg=TEXT, activebackground=BUTTON_HOVER, disabledforeground=TEXT_DIM,
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


class ButtonPanel:
     def __init__(
         self,
         root,
         logic
     ):
         self.root = root
         self.logic = logic
         # три групи: клавіатура зліва, оптимізатор по центру, Rec справа
         self.button_frame = tk.Frame(self.root, bg=BG)
         self.button_frame.pack(fill="x", padx=20, pady=(0, 14))
         # середня колонка забирає вільне місце: групи не обрізаються, коли
         # ліва (клавіатура) схована в режимі «Звичайна»
         self.button_frame.columnconfigure(1, weight=1)
         left, mid, right = (tk.Frame(self.button_frame, bg=BG) for _ in range(3))
         left.grid(row=0, column=0, sticky="w")
         mid.grid(row=0, column=1)
         right.grid(row=0, column=2, sticky="e")

         # клавіатура: шари <-> розкладка на екрані (scripts/zmk/keyboard_sync.py)
         self.keyboard_frame = left
         self.button_kb_write = make_button(left, "На клаву", self.logic.on_keyboard_write)
         self.button_kb_read = make_button(left, "З клави", self.logic.on_keyboard_read)
         self.button_start = make_button(mid, "Start", self.logic.toggle_optimization)
         self.button_reheat = make_button(
             mid, "Reheat",
             lambda: self.logic.processor.optimizer.reheat() if self.logic.processor.optimizer else None
         )
         # файли: розкладка (json) і картинка — завжди через діалог, юзер бачить куди
         self.button_open = make_button(right, "Відкрити…", self.logic.on_open)
         self.button_save = make_button(right, "Зберегти", self.logic.on_save)
         self.button_save_as = make_button(right, "Зберегти як…", self.logic.on_save_as)
         self.button_screenshot = make_button(right, "Скрін", self.logic.on_screenshot)
         # експорт в ОС (.klc / xkb / .keylayout) — лише «Звичайна» (core/export.py)
         self.button_export = make_button(right, "Експорт…", self.logic.on_export)
         for a, b in ((self.button_kb_write, self.button_kb_read), (self.button_start, self.button_reheat)):
             a.pack(side="left", padx=(0, 8))
             b.pack(side="left")
         for b in (self.button_open, self.button_save, self.button_save_as):
             b.pack(side="left", padx=(0, 8))
         self.button_screenshot.pack(side="left", padx=(8, 0))
         self.button_export.pack(side="left", padx=(8, 0))

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
    ):
        self.root = root
        self.root.title("Аналізатор розкладки")
        self.width = 900
        self.heigh = 470
        self.root.geometry(f"{self.width}x{self.heigh}")
        self.root.minsize(900, 450)
        self.root.configure(bg=BG)
        self.toasts = Toasts(self.root)  # неблокувальні жовті сповіщення
        self._weights_gen = 0            # номер перерахунку ваг (старі результати відкидаються)

        # the real domain object -- drag/drop mutates this directly, so
        # whatever the UI shows is exactly what a headless run would score
        self.statistic = statistic
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
        self.mode_bar.pack(fill="x", padx=20, pady=(12, 0))
        tk.Label(self.mode_bar, text="Клавіатура:", bg=BG, fg=TEXT_DIM,
                 font=(FONT, 11, "bold")).pack(side="left", padx=(2, 8))
        self.mode_buttons = {}
        for name in GEOMETRIES_ORDER:
            b = make_button(self.mode_bar, GEOMETRY_TITLES.get(name, name), lambda n=name: self.on_mode(n))
            b.pack(side="left", padx=(0, 6))
            self.mode_buttons[name] = b

        # tkinter / buttons
        self.status_var = tk.StringVar(value="Штраф: -")
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=BG,
            fg=TEXT,
            font=(FONT, 13, "bold"),
            anchor="w"
        )
        self.status_label.pack(fill="x", padx=22, pady=(10, 0))

        # вкладки: редактор розкладки (CYR з оптимізатора) або перегляд шару клавіатури
        self.tab_bar = tk.Frame(self.root, bg=BG)
        self.tab_bar.pack(fill="x", padx=20, pady=(8, 0))
        self.tabs = {}
        for name in ["Редактор"] + layer_view.lh.ORDER:
            b = make_button(self.tab_bar, name, lambda n=name: self.show_tab(n), small=True)
            b.pack(side="left", padx=(0, 4))
            self.tabs[name] = b
        # справа: скинути зміни шару / перечитати клавіатуру
        self.button_refresh_layers = make_button(self.tab_bar, "⟳ з клави", self.on_layers_refresh, small=True)
        self.button_refresh_layers.pack(side="right")
        self.button_reset_layer = make_button(self.tab_bar, "↺ скинути шар", self.on_layer_reset, small=True)
        self.button_reset_layer.pack(side="right", padx=(0, 4))

        # frame main
        self.board = tk.Frame(self.root, bg=PANEL, bd=0)
        self.board.pack(fill="both", expand=True, padx=20, pady=10)
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
        self.key_width = self.geometry["key_width"]
        self.key_height = self.geometry["key_height"]
        self.tolerance = self.geometry["tolerance_x"]
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
        panel = self.button_panel
        if self._zmk_mode():
            if not self.tab_bar.winfo_manager():
                self.tab_bar.pack(fill="x", padx=20, pady=(8, 0), before=self.board)
            if not panel.button_kb_write.winfo_manager():
                panel.button_kb_write.pack(side="left", padx=(0, 8))
                panel.button_kb_read.pack(side="left")
        else:
            if self.current_tab != "Редактор":
                self.show_tab("Редактор")
            self.tab_bar.pack_forget()
            panel.button_kb_write.pack_forget()
            panel.button_kb_read.pack_forget()
        if self._export_mode():
            if not panel.button_export.winfo_manager():
                panel.button_export.pack(side="left", padx=(8, 0))
        else:
            panel.button_export.pack_forget()
        self._fit_window()

    def _export_mode(self) -> bool:
        """Експорт в ОС — для геометрій, де клавіші мають фізичні назви (`key`)."""
        return any(p.get("key") for p in self.geometry["positions"])

    def _fit_window(self):
        """Вікно не вужче за дошку і ряд кнопок (інакше праві кнопки обрізаються)."""
        self.root.update_idletasks()
        cells = render.key_cells(self.geometry, self.geometry_name)
        board = max(x + width for _, x, _, width in cells) + 2 * layer_view.BASE_X + 40
        buttons = self.button_panel.button_frame.winfo_reqwidth() + 40 + 24
        panel = self.knob_frame.winfo_reqwidth() + 40 if getattr(self, "knobs_open", False) else 0
        needed = max(900, board, buttons, panel)
        self.root.minsize(needed, 450)
        if self.root.winfo_width() < needed:
            self.root.geometry(f"{needed}x{max(self.root.winfo_height(), self.heigh)}")

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
        base_x, base_y = layer_view.BASE_X, layer_view.BASE_Y  # та сама сітка, що й у вкладках шарів
        gap = render.GAP  # Відстань між кнопками
        # відпущена клавіша прилипає до найближчого слота в межах усієї його
        # клітинки (з проміжками), а не лише tolerance_x від центру
        self.tolerance = max(self.tolerance, math.hypot(self.key_width + gap, self.key_height + gap) / 2)

        cells = render.key_cells(self.geometry, self.geometry_name)
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
            widget.key = key
            widget.is_frozen = key.is_frozen
            style_key(widget)
            widget.current_slot = slot
            slot.current_key = widget

            # Бінди подій / Binds
            widget.bind("<Button-1>", self.on_drag_start)
            widget.bind("<B1-Motion>", self.on_drag_motion)
            widget.bind("<ButtonRelease-1>", self.on_drag_release)
            widget.bind("<Button-3>", self.toggle_freeze)
            # мітка AltGr лежить поверх клавіші — її події віддаємо клавіші
            for sequence, handler in (("<Button-1>", self.on_drag_start), ("<B1-Motion>", self.on_drag_motion),
                                      ("<ButtonRelease-1>", self.on_drag_release),
                                      ("<Button-3>", self.toggle_freeze)):
                widget.altgr_label.bind(sequence, lambda e, h=handler: h(SimpleNamespace(
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

    def _effective_moves(self) -> dict:
        state = self._knob_state()
        return knobs.apply(self.base_moves, state["values"], self.geometry, state["closeness"])

    def _build_knob_panel(self):
        self.knobs_open = False
        self.knob_bar = tk.Frame(self.root, bg=BG)
        self.knob_bar.pack(fill="x", padx=20, pady=(0, 6), before=self.button_panel.button_frame)
        self.button_knobs = make_button(self.knob_bar, "Детальніше ▸", self.toggle_knobs, small=True)
        self.button_knobs.pack(side="left")
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
            cell.grid(row=row, column=0, sticky="w", padx=(12, 10), pady=(4, 2))
            if knob.id == "closeness":
                title = tk.Checkbutton(cell, text=knob.title, variable=self.closeness_var,
                                       command=self.on_closeness_toggle, fg=TEXT, selectcolor=SLOT,
                                       activebackground=PANEL, activeforeground=TEXT, bd=0,
                                       highlightthickness=0, **label_opts)
            else:
                title = tk.Label(cell, text=knob.title, fg=TEXT, **label_opts)
            title.pack(anchor="w")
            metric = tk.Label(cell, fg=TEXT_DIM, anchor="w", bg=PANEL, font=(FONT, 9))
            metric.pack(anchor="w")
            tk.Label(self.knob_frame, text=knob.left, fg=TEXT_DIM, **label_opts).grid(
                row=row, column=1, sticky="e")
            scale = tk.Scale(self.knob_frame, from_=-knobs.LIMIT, to=knobs.LIMIT, resolution=0.05,
                             orient="horizontal", showvalue=0, length=220, sliderlength=18, width=12,
                             bg=PANEL, fg=TEXT, troughcolor=SLOT, activebackground=ACCENT,
                             highlightthickness=0, bd=0,
                             command=lambda _v, k=knob.id: self._on_knob_move(k))
            scale.set(state["values"].get(knob.id, 0.0))
            scale.grid(row=row, column=2, padx=6)
            scale.bind("<ButtonRelease-1>", lambda _e, k=knob.id: self.on_knob_release(k))
            tk.Label(self.knob_frame, text=knob.right, fg=TEXT_DIM, **label_opts).grid(
                row=row, column=3, sticky="w")
            step_label = tk.Label(self.knob_frame, fg=ACCENT, width=14, anchor="w", **label_opts)
            step_label.grid(row=row, column=4, sticky="w", padx=(10, 12))
            self.knob_rows[knob.id] = SimpleNamespace(scale=scale, step=step_label, metric=metric)
            self._on_knob_move(knob.id)
        self._set_knobs_state("disabled" if self.processor.is_running else "normal")
        self._update_knob_metrics()

    def toggle_knobs(self):
        self.knobs_open = not self.knobs_open
        if self.knobs_open:
            self.knob_frame.pack(fill="x", padx=20, pady=(0, 8), before=self.button_panel.button_frame)
            self.button_knobs_reset.pack(side="right")
            self.button_knobs.config(text="Детальніше ▾")
            self._update_knob_metrics()
            self._fit_window()
        else:
            self.knob_frame.pack_forget()
            self.button_knobs_reset.pack_forget()
            self.button_knobs.config(text="Детальніше ▸")
        # вікно росте/зменшується на висоту панелі, щоб клавіатуру не стискало
        self.root.update_idletasks()
        extra = self.knob_frame.winfo_reqheight() + 8
        width, height = self.root.winfo_width(), self.root.winfo_height()
        min_width = self.root.minsize()[0]
        if self.knobs_open:
            self.root.minsize(min_width, 450 + extra)
            height = max(height, self.heigh) + extra
        else:
            self.root.minsize(min_width, 450)
            height = max(self.heigh, height - extra)
        self.root.geometry(f"{max(width, min_width)}x{height}")

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

    def _rebuild_weights(self, what: str):
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
            self.toasts.show(f"Ваги змінено — {what}.\n"
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
                  panel.button_export):
            b.config(state=state)

    def _dialog_dir(self):
        return str(self._last_dir or layouts_dir())

    def _set_current_file(self, path):
        self.current_file = Path(path) if path else None
        self._last_dir = self.current_file.parent if self.current_file else self._last_dir
        name = f" — {self.current_file.name}" if self.current_file else ""
        self.root.title(f"Аналізатор розкладки{name}")

    def on_save(self):
        """Перезаписує відкритий/збережений файл; якщо його ще нема — як «Зберегти як…»."""
        if self.processor.is_running:
            return
        if self.current_file is None:
            return self.on_save_as()
        self._save_to(self.current_file)

    def on_save_as(self):
        if self.processor.is_running:
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Зберегти розкладку",
            initialdir=self._dialog_dir(), initialfile=f"layout_{self.geometry_name}_{stamp}.json",
            defaultextension=".json", filetypes=[("Розкладка (JSON)", "*.json")])
        if path:
            self._save_to(path)

    def _save_to(self, path):
        try:
            saved = self.processor.layout_save(self.layout, path)
        except OSError as error:
            messagebox.showerror("Зберегти", f"Не вдалося зберегти:\n{error}")
            return
        self._set_current_file(saved)
        self.status_var.set(f"Збережено: {saved}")
        self.toasts.show(f"Збережено: {saved}")

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
            self.board.pack(fill="both", expand=True, padx=20, pady=10,
                            before=self.button_panel.button_frame)
        else:
            self.board.pack_forget()
            self.layer_view.pack(fill="both", expand=True, padx=20, pady=10,
                                 before=self.button_panel.button_frame)
            self.layer_view.show(name)
        self.current_tab = name
        self._style_tabs()
        self._set_editor_buttons()
        self._notify_layout_changed()

    def _set_layers_dump(self, dump, source):
        self.layer_view.set_dump(dump, source)
        if self.current_tab != "Редактор":
            self.layer_view.show(self.current_tab)

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
        return render.save(self.layout.keys, self.geometry, self.geometry_name, path, title, subtitle)

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


def main(smoke_ms: int | None = None):
    """Запуск GUI. smoke_ms — закрити вікно через стільки мс (перевірка
    зібраного exe в CI: вікно будується повністю і процес виходить з кодом 0)."""
    _windows_setup()
    statistic = STATISTIC
    mode = settings.initial_mode(GEOMETRIES)  # запам'ятований режим; в exe типово «Звичайна»
    moves_config = load_moves(mode)
    root = tk.Tk()
    app = LayoutBuilderApp(
        root,
        statistic=statistic,
        moves_config=moves_config,
        on_layout_changed=make_score_display(statistic, moves_config),
        geometry_name=mode)
    if smoke_ms:
        root.after(smoke_ms, root.destroy)
    root.mainloop()
    return app


if __name__ == "__main__":
    main()
