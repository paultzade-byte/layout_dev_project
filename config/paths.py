"""Шляхи застосунку: ресурси (лише читання) і дані юзера (запис).

Ресурси — конфіги з репозиторію (`config/*.json|yaml`). У зібраному exe
(PyInstaller) вони лежать у `sys._MEIPASS`, тож шлях береться звідти.

Дані юзера — записані розкладки (Rec>>), пресети, вибраний режим. Вони
ніколи не пишуться в теку проєкту (у exe вона може бути лише для читання):
  Windows: %APPDATA%\\ukr-layout
  macOS:   ~/Library/Application Support/ukr-layout
  інше:    $XDG_CONFIG_HOME/ukr-layout (типово ~/.config/ukr-layout)
Змінна середовища LAYOUT_USER_DIR перекриває все (тести, портативний режим).
"""

import os
import sys
from pathlib import Path

APP_NAME = "ukr-layout"

PROJ_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
CONFIG_DIR = PROJ_DIR / "config"

# Rec>> до 2026-11-14 писав сюди; тепер — лише запасне джерело для Rec<<
# у режимі спліта (файл автора, у git не комітиться).
LEGACY_RECORDED_LAYOUT = CONFIG_DIR / "recorded_layout.json"


def user_data_dir() -> Path:
    override = os.environ.get("LAYOUT_USER_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def recorded_layout_path(geometry: str) -> Path:
    """Куди Rec>> пише розкладку для геометрії (окремо для кожного режиму)."""
    return user_data_dir() / f"recorded_{geometry}.json"


def recall_layout_path(geometry: str) -> Path | None:
    """Звідки Rec<< читає: файл юзера, а для спліта — ще старий
    config/recorded_layout.json, поки нового нема. None — нічого не записано."""
    path = recorded_layout_path(geometry)
    if path.exists():
        return path
    if geometry == "corne_42" and LEGACY_RECORDED_LAYOUT.exists():
        return LEGACY_RECORDED_LAYOUT
    return None
