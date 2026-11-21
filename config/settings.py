"""Налаштування юзера між запусками (user_data_dir()/settings.json).

Зараз — режим («Спліт» / «Звичайна») і частка CPU для пошуку. Зіпсований чи відсутній файл —
не помилка: беруться типові значення.
"""

import json
import os
import sys

from config.paths import user_data_dir

FILE_NAME = "settings.json"


def _path():
    return user_data_dir() / FILE_NAME


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(**changes) -> None:
    data = {**load(), **changes}
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # не змогли запам'ятати — не привід падати


def cpu_percent() -> int:
    """Скільки відсотків ядра бере пошук (меню «CPU» в GUI)."""
    from core import throttle
    value = load().get("cpu_percent")
    return value if value in throttle.CHOICES else throttle.DEFAULT


def initial_mode(geometries) -> str:
    """Режим на старті: LAYOUT_GEOMETRY > запам'ятований > типовий.
    Типовий — «Звичайна» в exe (для інших людей), у репо — з geometry.json."""
    from config.main_config import DEFAULT_GEOMETRY
    for mode in (os.environ.get("LAYOUT_GEOMETRY"), load().get("mode")):
        if mode in geometries:
            return mode
    return "generic_105_alpha" if getattr(sys, "frozen", False) else DEFAULT_GEOMETRY
