"""Обмеження CPU зсередини процесу: пошук працює частку часу, решту спить.

Оптимізація йде в одному потоці, тож бере щонайбільше одне ядро; share —
частка цього ядра (0.25 = чверть). Зовнішні засоби (cgroup, nice) у exe на
чужому комп'ютері недоступні, тому — простий шпаруватий цикл: після кожних
SLICE секунд роботи — сон, щоб робота/(робота+сон) = share.

tick() викликається на кожній ітерації: це лише perf_counter() (~0.1 мкс
проти ~250 мкс ітерації SA). share можна міняти на ходу (з потоку GUI).
Сон — через stop_event.wait(), щоб Stop спрацьовував одразу, а не після сну.
"""

import threading
import time

SLICE = 0.05  # с роботи між паузами: досить дрібно, щоб навантаження було рівним
CHOICES = (25, 50, 75, 100)  # відсотки в меню GUI
DEFAULT = 25                 # чужий комп'ютер може бути слабким — скромно за замовчуванням


class Throttle:
    def __init__(self, share: float = 1.0, stop_event: threading.Event | None = None):
        self.share = share
        self.stop_event = stop_event
        self._since = time.perf_counter()

    @property
    def share(self) -> float:
        return self._share

    @share.setter
    def share(self, value: float) -> None:
        self._share = min(1.0, max(0.05, float(value)))
        self.reset()

    def reset(self) -> None:
        """Почати рахувати роботу заново (на старті прогону: час до нього — не робота)."""
        self._since = time.perf_counter()

    def tick(self) -> None:
        if self._share >= 1.0:
            return
        now = time.perf_counter()
        busy = now - self._since
        if busy < SLICE:
            return
        # довгий проміжок між tick() — це не робота (простій, підготовка), а
        # не привід заснути на хвилину: рахуємо щонайбільше кілька SLICE
        busy = min(busy, 4 * SLICE)
        pause = busy * (1.0 - self._share) / self._share
        if self.stop_event is not None:
            self.stop_event.wait(pause)
        else:
            time.sleep(pause)
        self._since = time.perf_counter()
