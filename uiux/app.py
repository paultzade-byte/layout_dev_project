
import tkinter as tk
import math

from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC, ACTIVE
from core.layout_factory import build_layout, build_key_from_position
from core.models import Layout, Key
from core.scorer import MovementScoringEngine
from uiux.processors import OptimizationProcessor

from pathlib import Path
from log.loggers.state_hasher import StateHasher

# необхідно для перезапису при свопах
POSITIONS_BY_ID = {p["id"]: p for p in GEOMETRY_CONFIG["positions"]}

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

        return f"Score: {score:.2f}"
    return on_layout_changed

class Slot:
    def __init__(self, slot_id, x, y, width, height):
        self.id = slot_id
        self.x = x
        self.y = y
        self.center_x = x + width / 2
        self.center_y = y + height / 2
        self.current_key = None  # the tkinter widget permanently anchored here

class KeyLabel(tk.Label):
    key: Key
    is_frozen: bool
    current_slot: Slot

class LayoutBuilderApp:
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
        self.root.geometry("900x400")

        # the real domain object -- drag/drop mutates this directly, so
        # whatever the UI shows is exactly what a headless run would score
        self.layout = (layout if layout is not None else build_layout(GEOMETRY_CONFIG))
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}

        self.on_layout_changed = on_layout_changed

        # --- оптимізатор живе тут, а не на рівні модуля ---
        self.processor = OptimizationProcessor(statistic, moves_config)

        # tkinter / buttons
        self.status_var = tk.StringVar(value="Score: -")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#1e1e1e",
            fg="white",
            font=("Arial", 12, "bold"),
            anchor="w"
        ).pack(fill="x", padx=20, pady=(10, 0))

        # frame main
        self.board = tk.Frame(self.root, bg="#2b2b2b", relief="sunken", bd=2)
        self.board.pack(fill="both", expand=True, padx=20, pady=10)

        # frame for buttons
        self.button_frame = tk.Frame(self.root)
        self.button_frame.pack(fill="both", padx=20, pady=10)

        # Allow grid to stretch. Important for the very right button.
        self.button_frame.rowconfigure(3, weight=1)
        self.button_frame.columnconfigure(0, weight=1)
        self.button_frame.columnconfigure(4, weight=1)

        self.button_start = tk.Button(self.button_frame, text="Start", command=self.toggle_optimization)
        self.button_start.grid(row=0, column=1, columnspan=1, padx=(160,20), pady=10)

        self.button_reheat = tk.Button(self.button_frame, text="Reheat", command=lambda: self.processor.optimizer.reheat() if self.processor.optimizer else None)
        self.button_reheat.grid(row=0, column=2, columnspan=1, pady=10)

        self.button_record = tk.Button(self.button_frame, text="Rec>>", command=lambda: self.processor.layout_record(self.layout) if self.processor else None)
        self.button_record.grid(row=0, column=3, columnspan=2, sticky="se", padx=(0,20),  pady=10)
        self.button_record.config(state="normal")

        self.button_recall = tk.Button(self.button_frame, text="Rec<<", command=lambda: self.on_recall() if self.processor else None)
        self.button_recall.grid(row=0, column=5, columnspan=2, sticky="se", pady=10)
        self.button_record.config(state="normal")

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
        self.engine = MovementScoringEngine(self.layout.keys, moves_config)
        self.engine.update_layout(self.layout.keys)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def toggle_optimization(self):
        if not self.processor.is_running:
            self.button_start.config(text="Stop")
            self.button_record.config(state="disabled")
            self.button_recall.config(state="disabled")
            self.status_var.set("Оптимізую...")
            self.processor.start(
                self.layout,
                on_progress=self._on_progress,
                on_done=self._on_done,
            )
        else:
            self.processor.stop()
            self.status_var.set("Зупиняю...")
            self.button_record.config(state="normal")
            self.button_recall.config(state="normal")
            self.engine.prepare_statistics(statistic)
            self.score = self.engine.score().total_penalty
            self.status_var.set(f"Score: {self.score:.2f}")

    def _on_progress(self, layout, score, current_iteration):
        # викликається з робочого потоку -> завжди через root.after
        self.root.after(
            0,
            lambda: self.status_var.set(f"Оптимізую... ітерація {current_iteration}, score={score:.2f}")
        )

    def _update_layout(self, result_layout: Layout):
        self.layout = result_layout
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}
        self.redraw_keys()
        self.button_start.config(text="Start")
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
            widget.config(
                text=f"{key.char}\n(L)" if key.is_frozen else key.char,
                bg="tomato" if key.is_frozen else "lightgreen",
                font=("Arial", 9, "bold") if key.is_frozen else ("Arial", 14, "bold"),
            )

    def build_grid(self):
        """Побудова сітки слотів на основі геометрії"""
        base_x, base_y = 50, 40
        gap = 1  # Відстань між кнопками

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
                bg="#404040",
                width=self.key_width,
                height=self.key_height).place(x=x, y=y)
            self.slots.append(Slot(pos["id"], x, y, self.key_width, self.key_height))

    def populate_initial_keys(self):
        """Автоматична прив'язка літер до гріда
        Прив'язує кожен tkinter-віджет до реального доменного Key."""
        for pos, slot in zip(GEOMETRY_CONFIG["positions"], self.slots):
            key = self.keys_by_position[pos["id"]]
            #char = pos.get("default", "")
            widget = KeyLabel(
                self.board,
                text=f"{key.char}\n(L)" if key.is_frozen else key.char,
                bg="tomato" if key.is_frozen else "lightgreen",
                font=("Arial", 9, "bold") if key.is_frozen else ("Arial", 14, "bold"),
                relief="raised", bd=3  # board outline
            )
            widget.place(x=slot.x, y=slot.y, width=self.key_width, height=self.key_height)

            # Внутрішній стан кнопки
            widget.key = key
            widget.is_frozen = key.is_frozen
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
        widget.start_x = event.x
        widget.start_y = event.y
        widget.lift()

    def on_drag_motion(self, event):
        widget = event.widget
        if widget.is_frozen or self.processor.is_running: return

        # 1. Рухаємо перетягувану кнопку
        new_x = widget.winfo_x() - widget.start_x + event.x
        new_y = widget.winfo_y() - widget.start_y + event.y
        widget.place(x=new_x, y=new_y)

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
                bg_color = "tomato" if self.hovered_key.is_frozen else "lightgreen"
                self.hovered_key.config(bg=bg_color)

            # Підсвічуємо нову знайдену ціль
            if target_key:
                if target_key.is_frozen:
                    target_key.config(bg="darkred")  # Показуємо, що міняти не можна
                else:
                    target_key.config(bg="darkgreen")  # Ідеальна ціль для заміни

            # Запам'ятовуємо поточну ціль
            self.hovered_key = target_key

    def on_drag_release(self, event):

        # debug print layout hash to identify any differences
        # a = 'start' # locator
        # state_hasher = StateHasher()
        # state_hasher(self.layout, "app.on_drag_release." + a)

        widget = event.widget
        # don't allow drag release if frozen or running
        if widget.is_frozen or self.processor.is_running: return

        # Скидаємо підсвічування цільової кнопки
        if self.hovered_key and self.hovered_key.winfo_exists():
            bg_color = "tomato" if self.hovered_key.is_frozen else "lightgreen"
            self.hovered_key.config(bg=bg_color)
            self.hovered_key = None  # Очищаємо пам'ять

        drop_center_x = widget.winfo_x() + self.key_width / 2
        drop_center_y = widget.winfo_y() + self.key_height / 2

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
        # debug print layout hash to identify any differences
        # a = 'end'
        # state_hasher = StateHasher()
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
        self._notify_layout_changed()

    def _resync_key_geometry(self, key):
        """Оновлює геометричні поля key під його поточний position_id,
        зберігаючи char/is_frozen (доменний, а не геометричний стан)."""
        fresh = build_key_from_position(POSITIONS_BY_ID[key.position_id])
        key.x = fresh.x
        key.y = fresh.y
        key.row = fresh.row
        key.col = fresh.col
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
        char = widget.key.char
        if widget.key.is_frozen:
            widget.config(bg="tomato", text=f"{char}\n(L)", font=("Arial", 9, "bold"))
        else:
            widget.config(bg="lightgreen", text=char, font=("Arial", 14, "bold"))
        self._notify_layout_changed()

    def _notify_layout_changed(self):
        if self.on_layout_changed:
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
            widget.config(
                text=f"{key.char}\n(L)" if key.is_frozen else f"{key.char}",
                bg="tomato" if key.is_frozen else "lightgreen",
            )
        self._notify_layout_changed()

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
