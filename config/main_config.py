# config/main_config.py
from pathlib import Path
import json
import yaml
ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя' ,.ЙЦУКЕНГШЩЗХЇҐФІВАПРОЛДЖЄЯЧСМИТЬБЮ"

# "Чекбокси" (прапорці) логіки
LOWERING_ENABLED = True     # 1 - злизати все до нижнього регістру, 0 - залишити як є
STRICT_LETTERS_ONLY = False # 1 - тільки букви, пробіл, кома, крапка; 0 - розширена пунктуація
PROJ_DIR = Path(__file__).resolve().parent.parent
geometry_path = f"{PROJ_DIR}/config/geometry.json"
with open(geometry_path, "r", encoding="utf-8") as file:
    data = json.load(file)
ACTIVE = data["active_layout"]
GEOMETRY_CONFIG = data["layouts"][ACTIVE]
statistic_path = f"{PROJ_DIR}/config/statistic.json"
with open(statistic_path, "r", encoding="utf-8") as file:
    STATISTIC = json.load(file)
moves_config_path = f"{PROJ_DIR}/config/moves.yaml"
with open(moves_config_path, "r", encoding="utf-8") as file:
    MOVES_CONFIG = yaml.safe_load(file)

INITIAL_LAYOUT_C = ["Й", "Ц", "У", "К", "Е", "Ф", "І", "В", "А", "П", "Shft", "Я", "Ч", "С", "М", "И", "Н", "Г", "Ш", "Щ", "З", "Р", "О", "Л", "Д", "Ж", "Т", "Ь", "Б", "Ю", ",", "Shft", "Х", "Є", "Ї", "Ґ", "SPA", "CE"]
INITIAL_LAYOUT_L = ["й", "ц", "у", "к", "е", "ф", "і", "в", "а", "п", "Shft", "я", "ч", "с", "м", "и", "н", "г", "ш", "щ", "з", "р", "о", "л", "д", "ж", "т", "ь", "б", "ю", ".", "Shft", "х", "є", "ї", "ґ", "SPA", "CE"]
