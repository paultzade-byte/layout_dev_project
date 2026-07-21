import tkinter as tk
import math
import json
from config.main_config import GEOMETRY_CONFIG, INITIAL_LAYOUT_L


class Slot:
    def __init__(self, slot_id, x, y, width, height):
        self.id = slot_id
        self.x = x
        self.y = y
        self.center_x = x + width / 2
        self.center_y = y + height / 2
        self.current_key = None  # Посилання на віджет, який тут лежить


class LayoutBuilderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Аналізатор розкладки - Матриця")
        self.root.geometry("870x400")

        # UI Елементи (Повзунок працює незалежно через стандартний біндинг)
        self.slider = tk.Scale(self.root, from_=0, to=100, orient="horizontal", label="Вага параметра SFB")
        self.slider.pack(pady=10, fill="x", padx=20)

        self.board = tk.Frame(self.root, bg="#2b2b2b", relief="sunken", bd=2)
        self.board.pack(fill="both", expand=True, padx=20, pady=10)

        self.slots = []
        self.key_width = GEOMETRY_CONFIG["key_width"]
        self.key_height = GEOMETRY_CONFIG["key_height"]
        self.tolerance = GEOMETRY_CONFIG["tolerance_x"]

        self.build_grid()
        self.populate_initial_keys(INITIAL_LAYOUT_L)


        self.hovered_key = None  # Пам'ять для кнопки, на яку зараз наведено

    def build_grid(self):
        """Побудова сітки слотів на основі геометрії"""
        base_x, base_y = 50, 50
        gap = 5  # Відстань між кнопками

        for pos in GEOMETRY_CONFIG["positions"]:
            x = base_x + pos["offset_x"] + pos["col"] * (self.key_width + gap)
            y = base_y + pos["row"] * (self.key_height + gap)

            # Малюємо заглушку (контур слота) для візуалізації
            tk.Frame(self.board, bg="#404040", width=self.key_width, height=self.key_height).place(x=x, y=y)

            self.slots.append(Slot(pos["id"], x, y, self.key_width, self.key_height))

    def populate_initial_keys(self, chars):
        """Автоматична прив'язка літер до гріда"""
        for i, char in enumerate(chars):
            if i >= len(self.slots):
                break

            slot = self.slots[i]
            key_widget = tk.Label(
                self.board, text=char, bg="lightgreen", font=("Arial", 14, "bold"),
                relief="raised", bd=3
            )
            key_widget.place(x=slot.x, y=slot.y, width=self.key_width, height=self.key_height)

            # Внутрішній стан кнопки
            key_widget.char = char
            key_widget.is_frozen = False
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
        if widget.is_frozen:
            widget.config(bg="tomato", text=f"{widget.char}\n(L)", font=("Arial", 9, "bold"))
        else:
            widget.config(bg="lightgreen", text=widget.char, font=("Arial", 14, "bold"))


if __name__ == "__main__":
    root = tk.Tk()
    app = LayoutBuilderApp(root)
    root.mainloop()