"""core/throttle.py: пошук бере задану частку ядра, Stop не чекає кінця паузи."""

import threading
import time

from core.throttle import Throttle


def _busy_share(share, seconds=0.6):
    t = Throttle(share)
    wall0, cpu0 = time.perf_counter(), time.thread_time()
    while time.perf_counter() - wall0 < seconds:
        sum(range(200))          # «ітерація»
        t.tick()
    return (time.thread_time() - cpu0) / (time.perf_counter() - wall0)


def test_share_is_respected():
    # під квотою тестів (60%) потік і так не бере більше — тож перевіряємо низькі частки
    assert 0.15 < _busy_share(0.25) < 0.35


def test_full_share_never_sleeps():
    t = Throttle(1.0)
    start = time.perf_counter()
    for _ in range(100000):
        t.tick()
    assert time.perf_counter() - start < 0.5


def test_stop_interrupts_pause():
    stop = threading.Event()
    t = Throttle(0.05, stop)
    end = time.perf_counter() + 0.2
    while time.perf_counter() < end:   # 0.2 с роботи -> пауза ~3.8 с
        pass
    threading.Timer(0.1, stop.set).start()
    start = time.perf_counter()
    t.tick()
    assert time.perf_counter() - start < 1.0
