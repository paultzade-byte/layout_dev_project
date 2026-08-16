
import tkinter as tk
import math
import threading

from config.main_config import GEOMETRY_CONFIG, MOVES_CONFIG, STATISTIC, ACTIVE
from core.layout_factory import build_layout
from core.models import Layout
from uiux.processors import OptimizationProcessor

class Slot:
    def __init__(self, slot_id, x, y, width, height):
        self.id = slot_id
        self.x = x
        self.y = y
        self.center_x = x + width / 2
        self.center_y = y + height / 2
        self.current_key = None  # the tkinter widget permanently anchored here


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
        self.root.geometry("960x400")

        # the real domain object -- drag/drop mutates this directly, so
        # whatever the UI shows is exactly what a headless run would score
        self.layout = layout or build_layout(GEOMETRY_CONFIG)
        self.keys_by_position = {key.position_id: key for key in self.layout.keys}

        self.on_layout_changed = on_layout_changed

        # --- оптимізатор живе тут, а не на рівні модуля ---
        self.processor = OptimizationProcessor(statistic, moves_config)

        self.status_var = tk.StringVar(value="Score: -")
        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg="#1e1e1e",
            fg="white",
            font=("Arial", 12, "bold"),
            anchor="w"
        ).pack(fill="x", padx=20, pady=(10, 0))

        self.board = tk.Frame(self.root, bg="#2b2b2b", relief="sunken", bd=2)
        self.board.pack(fill="both", expand=True, padx=20, pady=10)

        self.button = tk.Button(self.root, text="Start", command=self.toggle_optimization)
        self.button.pack(pady=10)

        self.slots = []
        self.key_width = GEOMETRY_CONFIG["key_width"]
        self.key_height = GEOMETRY_CONFIG["key_height"]
        self.tolerance = GEOMETRY_CONFIG["tolerance_x"]
        self.stages = GEOMETRY_CONFIG["stages"]
        self.HAND_GAP_KEYS = 6
        self.build_grid()
        self.populate_initial_keys()
        self.hovered_key = None  # Пам'ять для кнопки, на яку зараз наведено
        self._notify_layout_changed()

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    def toggle_optimization(self):
        if not self.processor.is_running:
            self.button.config(text="Stop")
            self.status_var.set("Оптимізую...")
            self.processor.start(
                self.layout,
                on_progress=self._on_progress,
                on_done=self._on_done,
            )
        else:
            self.processor.stop()
            self.status_var.set("Зупиняю...")

    def _on_progress(self, layout, score, current_iteration):
        # викликається з робочого потоку -> завжди через root.after
        self.root.after(
            0,
            lambda: self.status_var.set(f"Оптимізую... ітерація {current_iteration}, score={score:.2f}")
        )

    def _on_done(self, result_layout: Layout):
        def update():
            self.layout = result_layout
            self.keys_by_position = {key.position_id: key for key in self.layout.keys}
            self.redraw_keys()
            self.button.config(text="Start")
            self._notify_layout_changed()
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
                text=f"{key.char}\n(L)" if key.is_frozen else f"{key.char}",
                bg="tomato" if key.is_frozen else "lightgreen",
                font=("Arial", 9, "bold") if key.is_frozen else ("Arial", 14, "bold"),
            )

    def build_grid(self):
        """Побудова сітки слотів на основі геометрії"""
        base_x, base_y = 50, 50
        gap = 5  # Відстань між кнопками

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
                x += self.HAND_GAP_KEYS * (self.key_width + gap)

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
            frozen = key.is_frozen
            key_widget = tk.Label(
                self.board,
                text=f"{key.char}\n(L)" if frozen else f"{key.char}",
                bg="tomato" if frozen else "lightgreen",
                font=("Arial", 9, "bold") if frozen else ("Arial", 14, "bold"),
                relief="raised", bd=4  # board outline
            )
            key_widget.place(x=slot.x, y=slot.y, width=self.key_width, height=self.key_height)

            # Внутрішній стан кнопки
            key_widget.key = key
            key_widget.is_frozen = frozen
            key_widget.current_slot = slot
            slot.current_key = key_widget

            # Бінди подій
            key_widget.bind("<Button-1>", self.on_drag_start)
            key_widget.bind("<B1-Motion>", self.on_drag_motion)
            key_widget.bind("<ButtonRelease-1>", self.on_drag_release)
            key_widget.bind("<Button-3>", self.toggle_freeze)

    def on_drag_start(self, event):
        widget = event.widget
        if widget.is_frozen: return
        widget.start_x = event.x
        widget.start_y = event.y
        widget.lift()

    def on_drag_motion(self, event):
        widget = event.widget
        if widget.is_frozen: return

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
        widget = event.widget
        if widget.is_frozen: return

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
            dist = math.hypot(drop_center_x - slot.center_x, drop_center_y - slot.center_y)
            if dist < min_distance:
                min_distance = dist
                closest_slot = slot

        # Логіка заміни залишається без змін
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

    def snap_to_slot(self, widget, slot):
        """Жорстка прив'язка віджета до координат слота"""
        widget.place(x=slot.x, y=slot.y)
        widget.current_slot = slot
        slot.current_key = widget

    def toggle_freeze(self, event):
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

if __name__ == "__main__":
    statistic = STATISTIC
    moves_config = MOVES_CONFIG

    root = tk.Tk()
    app = LayoutBuilderApp(root, statistic=statistic, moves_config=moves_config)
    root.mainloop()
