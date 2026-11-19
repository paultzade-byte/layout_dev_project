# config/main_config.py
"""Конфіги з репозиторію: геометрії, ваги, статистика корпусу.

Геометрій кілька (`geometry.json` -> `layouts`), у кожної свої ваги
(MOVES_FILES). Модульні GEOMETRY_CONFIG / MOVES_CONFIG — для активної
геометрії: `active_layout` з geometry.json, або змінна середовища
LAYOUT_GEOMETRY (для скриптів: `LAYOUT_GEOMETRY=generic_105_alpha python ...`).
GUI перемикає геометрію в рантаймі через geometry_config() / load_moves().
"""
import json
import os

import yaml

from config.paths import CONFIG_DIR, PROJ_DIR  # noqa: F401  (PROJ_DIR — для старих імпортів)

ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя' ,.ЙЦУКЕНГШЩЗХЇҐФІВАПРОЛДЖЄЯЧСМИТЬБЮ"

# "Чекбокси" (прапорці) логіки
LOWERING_ENABLED = True     # 1 - злизати все до нижнього регістру, 0 - залишити як є
STRICT_LETTERS_ONLY = False # 1 - тільки букви, пробіл, кома, крапка; 0 - розширена пунктуація

# Ваги для кожної геометрії. Спліт (corne_42) — ваги автора, не чіпати
# заради звичайної клавіатури; звичайна (generic_105_alpha) — свій файл.
MOVES_FILES = {
    "corne_42": "moves.yaml",
    "generic_105_alpha": "moves_standard.yaml",
}
# Назви режимів для GUI
GEOMETRY_TITLES = {
    "corne_42": "Спліт (Corne)",
    "generic_105_alpha": "Звичайна (ANSI)",
}

with open(CONFIG_DIR / "geometry.json", "r", encoding="utf-8") as file:
    _geometry_data = json.load(file)
GEOMETRIES = _geometry_data["layouts"]
DEFAULT_GEOMETRY = _geometry_data["active_layout"]


def geometry_config(name: str) -> dict:
    if name not in GEOMETRIES:
        raise KeyError(f"невідома геометрія {name!r}; є: {', '.join(GEOMETRIES)}")
    return GEOMETRIES[name]


def load_moves(name: str) -> dict:
    """Ваги для геометрії (свіжа копія з диска — її можна міняти)."""
    geometry_config(name)
    with open(CONFIG_DIR / MOVES_FILES[name], "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def start_layout(name: str):
    """Розкладка, з якої режим стартує в GUI: `start_layout` геометрії
    (файл у config/) поверх типової; без нього — типова (`default` позицій)."""
    from core.layout_factory import build_layout
    geometry = geometry_config(name)
    layout = build_layout(geometry)
    file_name = geometry.get("start_layout")
    if file_name:
        with open(CONFIG_DIR / file_name, "r", encoding="utf-8") as file:
            chars = {d["position_id"]: d["char"] for d in json.load(file)}
        for key in layout.keys:
            key.char = chars.get(key.position_id, key.char)
    return layout


ACTIVE = os.environ.get("LAYOUT_GEOMETRY") or DEFAULT_GEOMETRY
GEOMETRY_CONFIG = geometry_config(ACTIVE)
MOVES_CONFIG = load_moves(ACTIVE)

with open(CONFIG_DIR / "statistic.json", "r", encoding="utf-8") as file:
    STATISTIC = json.load(file)
# Частоти слів для hand_runs (scripts/word_counter.py). Рахуються по вибірці
# корпусу, тому масштабуються до повного корпусу, як і n-грами в statistic.json.
word_stats_path = CONFIG_DIR / "word_stats.json"
if word_stats_path.exists():
    with open(word_stats_path, "r", encoding="utf-8") as file:
        _word_stats = json.load(file)
    _scale = 1.0 / _word_stats["meta"]["sample_fraction"]
    STATISTIC["words"] = {w: n * _scale for w, n in _word_stats["words"].items()}

with open(CONFIG_DIR / "mutator_config.json", "r", encoding="utf-8") as file:
    MUTATOR_CONFIG = json.load(file)

INITIAL_LAYOUT_C = ["Й", "Ц", "У", "К", "Е", "Ф", "І", "В", "А", "П", "Shft", "Я", "Ч", "С", "М", "И", "Н", "Г", "Ш", "Щ", "З", "Р", "О", "Л", "Д", "Ж", "Т", "Ь", "Б", "Ю", ",", "Shft", "Х", "Є", "Ї", "Ґ", "SPA", "CE"]
INITIAL_LAYOUT_L = ["й", "ц", "у", "к", "е", "ф", "і", "в", "а", "п", "Shft", "я", "ч", "с", "м", "и", "н", "г", "ш", "щ", "з", "р", "о", "л", "д", "ж", "т", "ь", "б", "ю", ".", "Shft", "х", "є", "ї", "ґ", "SPA", "CE"]
