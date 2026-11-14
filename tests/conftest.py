"""Спільне для тестів. Запуск — під cpulimit (CLAUDE.md):
    cpulimit -l 60 -f -m -q -- .venv/bin/python -m pytest
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
