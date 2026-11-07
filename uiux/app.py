
import tkinter as tk
from tkinter import ttk, messagebox
import math
import sys
import threading

from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC, ACTIVE
from core.layout_factory import build_layout, build_key_from_position
from core.models import Finger, Layout, Key
from core.scorer import MovementScoringEngine
from uiux.processors import OptimizationProcessor
from uiux import layer_view
from uiux.widgets import RoundButton
from pathlib import Path
# keeping this dead import for possible bedugging process
#from log.loggers.state_hasher import StateHasher

# необхідно для перезапису при свопах
POSITIONS_BY_ID = {p["id"]: p for p in GEOMETRY_CONFIG["positions"]}
ZMK_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "zmk"
# штраф показується в тій самій шкалі, що й у scripts/ (x1e8)
SCORE_SCALE = 1e8

# --- тема ---------------------------------------------------------------
BG = "#16181d"            # вікно
PANEL = "#1f2229"         # дошка
SLOT = "#2a2e37"          # порожній слот
TEXT = "#e6e8ee"
TEXT_DIM = "#8b91a0"
ACCENT = "#7aa2f7"
BUTTON = "#2c313c"
BUTTON_HOVER = "#3a4050"
KEY_TEXT = "#16181d"
FROZEN_BG = "#2c313c"     # заморожена клавіша: темна з бурштиновою рамкою
FROZEN_FG = "#f6c177"
DROP_OK = "#ffffff"       # підсвітка цілі при перетягуванні
DROP_BLOCKED = "#eb6f92"
# зони пальців — однакові для обох рук
FINGER_COLORS = {
    Finger.PINKY: "#c4a7e7",
    Finger.RING: "#9ccfd8",
    Finger.MIDDLE: "#f6c177",
    Finger.INDEX: "#a6da95",
    Finger.THUMB: "#8b91a0",
}
FONT = "Ubuntu"
KEY_FONT = (FONT, 17, "bold")


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
    widget.config(
        text=key.char, bg=bg, fg=fg, font=KEY_FONT,
        highlightthickness=2, highlightbackground=border, highlightcolor=border,
    )


def make_button(parent, text, command, small=False):
    """Кнопка апки: заокруглена (uiux.widgets.RoundButton), hover — сама."""
    return RoundButton(
        parent, text=text, command=command, font=(FONT, 9 if small else 11, "bold"),
        bg=BUTTON, fg=TEXT, activebackground=BUTTON_HOVER, disabledforeground=TEXT_DIM,
        padx=8 if small else 16, pady=3 if small else 6, radius=6 if small else 8,
    )

def make_score_display(statistic, moves_config):
    engine_holder = {}

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
    def __init__(self, slot_id, x, y, width, height):
        self.id = slot_id
        self.x = x
        self.y = y
        self.center_x = x + width / 2
        self.center_y = y + height / 2
        self.current_key = None  # the tkinter widget permanently anchored here
        self.finger = build_key_from_position(POSITIONS_BY_ID[slot_id]).finger


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
         for col in (0, 2):
             self.button_frame.columnconfigure(col, weight=1, uniform="side")
         left, mid, right = (tk.Frame(self.button_frame, bg=BG) for _ in range(3))
         left.grid(row=0, column=0, sticky="w")
         mid.grid(row=0, column=1)
         right.grid(row=0, column=2, sticky="e")

         # клавіатура: шари <-> розкладка на екрані (scripts/zmk/keyboard_sync.py)
         self.button_kb_write = make_button(left, "На клаву", self.logic.on_keyboard_write)
         self.button_kb_read = make_button(left, "З клави", self.logic.on_keyboard_read)
         self.button_start = make_button(mid, "Start", self.logic.toggle_optimization)
         self.button_reheat = make_button(
             mid, "Reheat",
             lambda: self.logic.processor.optimizer.reheat() if self.logic.processor.optimizer else None
         )
         self.button_record = make_button(
             right, "Rec>>",
             lambda: self.logic.processor.layout_record(self.logic.layout) if self.logic.processor else None
         )
         self.button_recall = make_button(right, "Rec<<", lambda: self.logic.on_recall() if self.logic.processor else None)
         for a, b in ((self.button_kb_write, self.button_kb_read), (self.button_start, self.button_reheat),
                      (self.button_record, self.button_recall)):
             a.pack(side="left", padx=(0, 8))
             b.pack(side="left")

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
    ):
        self.root = root
        self.root.title("Аналізатор розкладки - Матриця")
        self.width = 900
        self.heigh = 470
        self.root.geometry(f"{self.width}x{self.heigh}")
        self.root.minsize(900, 450)
        self.root.configure(bg=BG)

        # the real domain object -- drag/drop mutates this directly, so
        # whatever the UI shows is exactly what a headless run would score
        self.layout = (layout if layout is not None else build_layout(GEOMETRY_CONFIG))
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}

        self.on_layout_changed = on_layout_changed

        # --- оптимізатор живе тут, а не на рівні модуля ---
        self.processor = OptimizationProcessor(statistic, moves_config)

        # tkinter / buttons
        self.status_var = tk.StringVar(value="Штраф: -")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=BG,
            fg=TEXT,
            font=(FONT, 13, "bold"),
            anchor="w"
        ).pack(fill="x", padx=22, pady=(12, 0))

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
        self._style_tabs()
        self.button_reset_layer.config(state="disabled")

        # layout
        self.slots = []
        self.key_width = GEOMETRY_CONFIG["key_width"]
        self.key_height = GEOMETRY_CONFIG["key_height"]
        self.tolerance = GEOMETRY_CONFIG["tolerance_x"]
        self.stages = GEOMETRY_CONFIG["stages"]
        self.HAND_GAP_KEYS = 4
        self.build_grid()
        self.populate_initial_keys()
        self.hovered_key = None  # Пам'ять для кнопки, на яку зараз наведено
        self._notify_layout_changed()

        # scoring
        self.engine = MovementScoringEngine(self.layout.keys, moves_config)
        # heavy / depends on statistic / recalled once
        self.engine.prepare_statistics(statistic)
        # refreshing after mutation/swap
        self.engine.update_layout(self.layout.keys)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def toggle_optimization(self):
        if not self.processor.is_running:
            self.button_panel.button_start.config(text="Stop")
            self.button_panel.button_record.config(state="disabled")
            self.button_panel.button_recall.config(state="disabled")
            self._set_keyboard_buttons("disabled")
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
        self.button_panel.button_record.config(state="normal")
        self.button_panel.button_recall.config(state="normal")
        self._set_keyboard_buttons("normal")
        self._set_editor_buttons()
        self._notify_layout_changed()

    def _on_done(self, result_layout: Layout):
        update = lambda: self._update_layout(result_layout)
        self.root.after(0, update)

    def redraw_keys(self):
        """Перемальовує клавіші на дошці згідно з поточним self.layout після оптимізації."""
        for pos, slot in zip(GEOMETRY_CONFIG["positions"], self.slots):
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
        gap = 6  # Відстань між кнопками
        # відпущена клавіша прилипає до найближчого слота в межах усієї його
        # клітинки (з проміжками), а не лише tolerance_x від центру
        self.tolerance = max(self.tolerance, math.hypot(self.key_width + gap, self.key_height + gap) / 2)

        for pos in GEOMETRY_CONFIG["positions"]:
            if self.stages == 1:
                x = base_x + pos["offset_x"] + pos["col"] * (self.key_width + gap)
                y = base_y + pos["row"] * (self.key_height + gap)
            elif self.stages == 0:
                x = base_x + pos["col"] * (self.key_width + gap)
                y = base_y + pos["row"] * (self.key_height + gap)
            else:
                raise KeyError

            if pos.get("hand") == "R":
                if ACTIVE == "generic_105_alpha":
                    x = x
                elif ACTIVE == "corne_42":
                    x += 400  # self.HAND_GAP_KEYS + self.key_width + gap
                else:
                    raise KeyError("Unknown active layout")

            # Малюємо заглушку (контур слота) для візуалізації
            tk.Frame(
                self.board,
                bg=SLOT,
                width=self.key_width,
                height=self.key_height).place(x=x, y=y)
            self.slots.append(Slot(pos["id"], x, y, self.key_width, self.key_height))

    def populate_initial_keys(self):
        """Автоматична прив'язка літер до гріда
        Прив'язує кожен tkinter-віджет до реального доменного Key."""
        for pos, slot in zip(GEOMETRY_CONFIG["positions"], self.slots):
            key = self.keys_by_position[pos["id"]]
            #char = pos.get("default", "")
            widget = KeyLabel(self.board, relief="flat", bd=0, cursor="hand2")
            widget.place(x=slot.x, y=slot.y, width=self.key_width, height=self.key_height)

            # Внутрішній стан кнопки
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
        fresh = build_key_from_position(POSITIONS_BY_ID[key.position_id])
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
        widget.place(x=slot.x, y=slot.y)
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


    # ------------------------------------------------------------------
    # Recall the layout
    # ------------------------------------------------------------------

    def on_recall(self):
        path = Path(__file__).resolve().parents[1] / "config" / "recorded_layout.json"
        data = self.processor.layout_recall(path)
        self._apply_recorded_state(data)

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
        for b in (self.button_panel.button_start, self.button_panel.button_reheat,
                  self.button_panel.button_record, self.button_panel.button_recall):
            b.config(state=state)
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
            messagebox.showinfo("Клавіатура", "Клавіатура вже збігається з розкладкою на екрані.")
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
        messagebox.showinfo("На клаву", "\n".join(lines))

    def on_layers_write(self):
        if not self.layer_view.pending():
            messagebox.showinfo("На клаву", "Незаписаних змін у шарах немає.")
            return
        ks = self._keyboard_sync()
        working, base = self.layer_view.dump, self.layer_view.base
        self._keyboard_task("Читаю клавіатуру...", lambda: ks.prepare_layers(working, base),
                            lambda plan: self._confirm_layers_write(ks, plan))

    def _confirm_layers_write(self, ks, plan):
        self._set_keyboard_buttons("normal")
        self._notify_layout_changed()
        if not plan.count:
            messagebox.showinfo("На клаву", "Клавіатура вже має ці зміни.")
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
        messagebox.showinfo("На клаву", "\n".join([
            f"Записано {plan.count} клавіш у {', '.join(plan.changes)}.", "",
            f"відкат: {rel(out['before'])}", f"html: {rel(out['html'])}"]))

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
    def export_svg(self):
        width = self.width
        heigh = self.heigh
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewbox="0 0 {width} {heigh}">']
        pass

    def save_layout_dialog():
        pass


if __name__ == "__main__":
    statistic = STATISTIC
    moves_config = MOVES_CONFIG
    root = tk.Tk()
    app = LayoutBuilderApp(
        root,
        statistic=statistic,
        moves_config=moves_config,
        on_layout_changed=make_score_display(statistic, moves_config))
    root.mainloop()
