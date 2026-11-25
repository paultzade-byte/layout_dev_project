"""Спільне для тестів. Запуск — під квотою CPU (CLAUDE.md):
    systemd-run --user --scope -q -p CPUQuota=60% nice -n 10 .venv/bin/python -m pytest
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# дані юзера — у тимчасову теку, щоб тести не чіпали справжні записи
os.environ.setdefault("LAYOUT_USER_DIR", tempfile.mkdtemp(prefix="ukr-layout-test-"))

from config.main_config import GEOMETRIES, STATISTIC, geometry_config, load_moves  # noqa: E402
from core.layout_factory import build_layout  # noqa: E402
from core.scorer import MovementScoringEngine  # noqa: E402


@pytest.fixture(scope="session")
def statistic():
    return STATISTIC


@pytest.fixture(scope="session", params=sorted(GEOMETRIES))
def geometry_name(request):
    return request.param


@pytest.fixture(scope="session")
def engines(statistic):
    """Один підготовлений engine на геометрію (prepare_statistics дорогий)."""
    cache = {}

    def get(name):
        if name not in cache:
            layout = build_layout(geometry_config(name))
            cache[name] = MovementScoringEngine(layout.keys, load_moves(name)).prepare_statistics(statistic)
        return cache[name]
    return get


@pytest.fixture(autouse=True)
def _finish_threads_and_collect():
    """Після тесту: дочекатися фонових потоків (перерахунок ваг, пошук) і зібрати сміття
    в головному потоці. Інакше Tk-об'єкти закритих вікон (тести створюють десятки
    tk.Tk()) прибирає збирач сміття у фоновому потоці наступного тесту — на Windows це
    аварія Tcl (CI 2026-11-25: «Windows fatal exception 0x80000003» у scorer з потоку
    _rebuild_weights, далі «Can't find a usable tk.tcl»). У програмі вікно одне й живе
    весь час — там такого нема."""
    import gc
    import threading
    import time
    yield
    deadline = time.monotonic() + 30
    for t in threading.enumerate():
        if t is not threading.main_thread() and t.is_alive():
            t.join(timeout=max(0.0, deadline - time.monotonic()))
    gc.collect()
